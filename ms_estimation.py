import json
import requests
import os
import base64
import sys
from requests.auth import HTTPBasicAuth
from datetime import datetime
import logging
import sys
import random
import time
import re

############

_APPD_CONTROLER_URL=None
_APPD_CONTROLLER_PORT=None
_APPD_USER=None
_APPD_PWD=None
_APPD_ACCOUNT_NAME=None
_APPD_MS_NODE_REGEX=[]
_APPD_PID_THRESHOLD=250

def getNodeRegex():
    envs = os.environ.keys()
    for evv in envs:
        if evv.startswith('APPD_MS_NODE_REGEX_'):
            _APPD_MS_NODE_REGEX.append(os.environ.get(evv))
    
def checkNodeNameforMs(nodeName):
    for r in _APPD_MS_NODE_REGEX:
        if re.search(r,nodeName):
            return True
    return False

def getApplicationsComLogin():
    bUser = _APPD_USER+"@"+_APPD_ACCOUNT_NAME
    #params = {'output':'json'}
    params = {
    'output':'json',
    'time-range-type':'BEFORE_NOW',
    'duration-in-mins':'5'
    }
    controllerUrl = _APPD_CONTROLER_URL+':'+_APPD_CONTROLLER_PORT
    r = requests.get(controllerUrl+'/controller/rest/applications', auth=HTTPBasicAuth(bUser, _APPD_PWD),params=params)
    if (r.status_code==200):
        return json.loads(r.text)    
    else:
        raise Exception("Error Getting node data: "+ str(r.status_code))

def getAllNodesFromApplicationComLogin(applicationId):
    bUser = _APPD_USER+"@"+_APPD_ACCOUNT_NAME
    apiURI = '/controller/rest/applications/'+str(applicationId)+'/nodes'
    params = {
        'output':'json',
        'time-range-type':'BEFORE_NOW',
        'duration-in-mins':'5'
        }
    
    controllerUrl = _APPD_CONTROLER_URL+':'+_APPD_CONTROLLER_PORT
    r = requests.get(controllerUrl+apiURI,auth=HTTPBasicAuth(bUser, _APPD_PWD),params=params)
    if (r.status_code==200):
        return json.loads(r.text)    
    else:
        raise Exception("Error Getting Application data: "+ str(r.status_code))

def login(_session):
    _session = requests.Session()
    controllerUrl = _APPD_CONTROLER_URL+':'+_APPD_CONTROLLER_PORT
    _login_data = {'userName': _APPD_USER,
                   'password': base64.standard_b64encode(bytes(_APPD_PWD, encoding='utf-8')).decode("UTF-8"), 'accountName': _APPD_ACCOUNT_NAME}
    _result = _session.post(controllerUrl +
                            '/controller/auth?action=login', _login_data, timeout=10)

    if _result.status_code != 200:
        print('ERRO ao realizar login no SITE, verifique os dados do usuário')
        print('- Status Code:', _result.status_code)
        raise Exception("ERRO ao realizar login no SITE, verifique os dados do usuário ")
    else:
        return _session


def getNodeMetaInfo(_session,applicationId,nodeId):
    controllerUrl = _APPD_CONTROLER_URL+':'+_APPD_CONTROLLER_PORT
     # Retrieve the CSRF token first
    _session.get(controllerUrl+'/controller/#/location=APP_NODE_ARE_DASH&timeRange=last_5_minutes.BEFORE_NOW.-1.-1.60&application='+str(applicationId)+'&node='+str(nodeId))  # sets cookie

    if 'csrftoken' in _session.cookies:
        # Django 1.6 and up
        csrftoken = _session.cookies['X-CSRF-TOKEN']
    else:
        # older versions
        csrftoken = _session.cookies['X-CSRF-TOKEN']

    
    # Pass CSRF token both in login parameters (csrfmiddlewaretoken)
    # and in the session cookies (csrf in client.cookies)
    
    headers_dict = {"X-CSRF-TOKEN": csrftoken,"Referer":_APPD_CONTROLER_URL+"/controller/"}
    r = _session.get(controllerUrl+'/controller/restui/nodeUiService/node/'+str(nodeId), headers=headers_dict)

    if (r.status_code==200):
        return json.loads(r.text)    
    else:
        if (r.status_code==204):
            return json.loads("[]")
        else:
            print(r.text)
            raise Exception("Error Getting node data: "+ str(r.status_code))

def hasContainerId(metainfo):
    for obj in metainfo:
        if obj['name'] == 'appdynamicsContainerId':
            return True
    return False

def filterNodes(appName,allNodes):
    retNodes = []
    for n in allNodes:
        if n['agentType'] != 'MACHINE_AGENT':
            retNodes.append(n)
        else:
            log('No App Agent in: '+'App:'+appName+' node:'+ n['name']+' -> '+n['agentType'])
    return retNodes

def checkOtherVariables(metainfo,nodeName):
    ms = 'false'
    if hasContainerId(metainfo):  #CHECK IF METADADA HAS CONTAINERID
        ms = 'true'
    else: # CHECK IF NODENAME HAS ANY PATTERN THAT MATCHES A MICROSERVICE PATTERN
        if checkNodeNameforMs(nodeName):
            ms='true'
    return ms

def processApplications(samples):

    _FILE = open("lics.txt", "w")
    _FILE.write('application|tier|nodeName|nodeAgentType|microservice|liccount|pid|historical\n')
    appCount=1
    nodeCount=1    

    try:
        applications = []

        _session = login(requests.Session())
        if (samples==1):
            if len(sys.argv) == 3:
                applications.append(
                    {'name':'tst','id':sys.argv[2]}
                    )
            else:
                applications = getApplicationsComLogin()
        else:
            applications = getApplicationsComLogin()

        totalApplications = len(applications)
        for app in applications:
            appName = app['name']
            appId = app['id']
            nodesDaApp = getAllNodesFromApplicationComLogin(appId)
            nodesDaAppFilter = filterNodes(appName,nodesDaApp)
            log('Processando Application...'+appName+'  ['+str(appCount)+'/'+str(totalApplications)+'] total de Nodes:['+str(len(nodesDaApp))+'] Nodes com AppAgent ['+str(len(nodesDaAppFilter))+']')        
            nodeCount = nodeCount + len(nodesDaAppFilter)
            for node in nodesDaAppFilter:
                nodeId = node['id']
                nodeName = node['name']
                nodeAgentType = node['agentType']
                tierName = node['tierName']

                lixo=getNodeMetaInfo(_session,appId,nodeId)
                metainfo = lixo['metaInfo']
                lunits = lixo['numberOfLicenseUnits']
                config = lixo['lastKnownTierAppConfig']
                historical = lixo['historical']

                minfoPID = next(
                    (obj for obj in metainfo
                    if obj['name'] == 'ProcessID'),
                    None
                )
                isms='false'

                if minfoPID != None:
                    #if PID <= PIS THRESHOLD = MICROSERVICE
                    if str(minfoPID['value']) =='':
                        mPID=0
                    else:
                        mPID=int(str(minfoPID['value']))

                    if mPID <= int(_APPD_PID_THRESHOLD):
                        isms='true'
                    else:
                        isms = checkOtherVariables(metainfo,nodeName)
                else:
                    log('NO PID ->'+config+'|'+nodeName+'|'+nodeAgentType+' lets check other variables')
                    mPID=-1
                    isms = checkOtherVariables(metainfo,nodeName)
                    
                _FILE.write(config+'|'+nodeName+'|'+nodeAgentType+'|'+isms+'|'+str(lunits)+'|'+str(mPID)+'|'+str(historical))    
                _FILE.write('\n')


                #rwait = random.randint(0, 1)
                rwait = random.random()

                time.sleep(rwait)

            appCount+=1    
            if (samples > 0):
                if (appCount >=samples ):
                    break

    finally:
        _FILE.flush()
        _FILE.close()    
        log("Total Apps:"+str(appCount))
        log("Total Nodes:"+str(nodeCount))                    
    return 


def log(msg):
    print(msg)
    _LOG_FILE.write(msg)
    _LOG_FILE.write('\n')


def validateEnv():
    if not _APPD_CONTROLER_URL:
        print(" APPD_CONTROLER_URL MISSING")
        return False

    if not _APPD_CONTROLLER_PORT:
        print(" APPD_CONTROLLER_PORT MISSING")
        return False

    if not _APPD_USER:
        print(" APPD_USER MISSING")
        return False   

    if not _APPD_PWD:
        print(" APPD_PWD MISSING")
        return False 

    if not _APPD_ACCOUNT_NAME:
        print(" APPD_ACCOUNT_NAME MISSING")
        return False 

    if not _APPD_ACCOUNT_NAME:
        _APPD_PID_THRESHOLD=1


    return True

_APPD_CONTROLER_URL=os.environ.get('APPD_CONTROLER_URL')
_APPD_CONTROLLER_PORT=os.environ.get('APPD_CONTROLLER_PORT')
_APPD_USER=os.environ.get('APPD_USER')
_APPD_PWD=os.environ.get('APPD_PWD')
_APPD_ACCOUNT_NAME=os.environ.get('APPD_ACCOUNT_NAME')
_APPD_PID_THRESHOLD=os.environ.get('APPD_PID_THRESHOLD')


if (validateEnv()):

    getNodeRegex()

    _LOG_FILE = open("run.log", "w")

    n = len(sys.argv)
    sample = 0
    if n == 2 or n==3:
        log("Sampling with : "+sys.argv[1])
        sample = int(sys.argv[1])
    else:
        log("Get data for all applications")

    try:
        log("------------------")
        log('nodename regex expressions:')
        log(str(_APPD_MS_NODE_REGEX))
        log('PID Threshold:')
        log(str(_APPD_PID_THRESHOLD))
        log("------------------")
        now = datetime.now() # current date and time
        date_time = now.strftime("%m/%d/%Y, %H:%M:%S")
        log("Começando....: "+str(date_time))

        result = processApplications(sample)

        now = datetime.now() # current date and time
        date_time = now.strftime("%m/%d/%Y, %H:%M:%S")
        log("Finlizado em: "+str(date_time))    

    except Exception as e:    
        logging.exception("Something awful happened!")
      
    finally:
        _LOG_FILE.flush()
        _LOG_FILE.close()