import socket
import socks
from urllib.request import Request,urlopen
from collections import deque
from copy import copy
from bs4 import BeautifulSoup
import requests,re,datetime,sys,getopt,pymongo,time
from requests_futures.sessions import FuturesSession
from fake_useragent import UserAgent
import random


class SteamData:
    R_URL = "http://store.steampowered.com/appreviews/{1}?json=1&filter=recent&start_offset={0}"
    GL_URL = "http://api.steampowered.com/ISteamApps/GetAppList/v0002/?key=STEAMKEY&format=json"
    G_URL = "http://store.steampowered.com/api/appdetails?appids={0}"
    U_URL = "http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={1}&steamids={0}"
    UA_URL = "http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/?appid={1}&key={2}&steamid={0}"
    US_URL = "http://api.steampowered.com/ISteamUserStats/GetUserStatsForGame/v0002/?appid={1}&key={2}&steamid={0}"
    UO_URL = "http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={1}&steamid={0}&format=json"
    UB_URL = "http://api.steampowered.com/ISteamUser/GetPlayerBans/v1/?key={1}&steamids={0}"
    UF_URL = "http://api.steampowered.com/ISteamUser/GetFriendList/v0001/?key={1}&steamid={0}&relationship=friend"
    topSellerList_URL = "http://store.steampowered.com/search/?filter=topsellers&page={0}"

    APIKEY= "your app key"
    authors = set()
    authorsList = []
    currentAppId = -1
    future_req = False
    grequests_imported = False
    torOff = True
    proxy = {"ip":"0","port":"0"}
    chunksize = 100

    def __init__(self):
        self.client = pymongo.MongoClient()
        self.db = self.client.steam
        self.setProxies()

    def setProxies(self):
        # Retrieve latest proxies
        proxies = []
        while True:
            try:
                proxies_req = requests.get('https://www.sslproxies.org/')
                break
            except:
                time.sleep(1)
                continue
        #ua = UserAgent()
        #proxies_req.add_header('User-Agent',ua)
        #proxies_doc = urlopen(proxies_req).read().decode('utf8')

        soup = BeautifulSoup(proxies_req.text, 'html.parser')
        proxies_table = soup.find(id='proxylisttable')

        # Save proxies in the array
        for row in proxies_table.tbody.find_all('tr'):
            proxies.append({
            'ip':   row.find_all('td')[0].string,
            'port': row.find_all('td')[1].string
            })

        # Choose a random proxy
        proxy = proxies[random.randint(0, len(proxies) - 1)]
        self.proxy = proxy


    def asyncRequest(self,reqUrl=None,urlParams=None,targetArr=None):
        taskUrlname = reqUrl.split("/")[3]
        t1 = time.time()
        while True:
            if self.future_req:
                session = FuturesSession(max_workers=self.chunksize)
                if urlParams == None:
                    rs = (session.get(reqUrl.format(i)) for i in targetArr)
                else:
                    rs = (session.get(reqUrl.format(i,*urlParams)) for i in targetArr)
                try:
                    myresponse = list(map(lambda x:x.result(),rs))
                except:
                    continue
            else:
                if not self.grequests_imported:
                    import grequests
                    grequests_imported = True
                if urlParams == None:
                    rs = (grequests.get(reqUrl.format(i), proxies=self.proxy,timeout=10) for i in targetArr)
                else:
                    rs = (grequests.get(reqUrl.format(i,*urlParams),proxies=self.proxy,timeout=10) for i in targetArr)
                try:
                    myresponse = grequests.map(rs)
                except:
                    continue
            status =  [int(i.status_code==200) for i in myresponse if i != None]
            httpstatus = sum(status)
            print("sum of http200Status {0} : {1}".format(taskUrlname,httpstatus))
            if taskUrlname == "ISteamUserStats":
                httpstatus += 1
            self.proxySetting()
            
            if len(status) != 0 and httpstatus != 0:
                break
        #print("t1",time.time()-t1)
        return myresponse,httpstatus


    def onTorBrowser(self):
        self.torOff = True

    def proxySetting(self):
        if self.torOff == True:
            self.setProxies()
            print(self.proxy)
            return 

        socks.set_default_proxy(socks.SOCKS5,"localhost",9150)
        socket.socket = socks.socksocket
        ipch = 'http://icanhazip.com'
        print(urlopen(ipch).read())

    def newAppList(self):
        appList = requests.get(self.GL_URL).json()["applist"]["apps"]
        return appList

    def getAppids(self):
        return self.db.appList.distinct("appid")
    


    def updateAppList(self):
        newApplist = self.newAppList()
        newAppset = set([i["appid"] for i in newApplist])
        curAppset = set(self.getAppids())
        addtionalAppids = list(newAppset - curAppset)
        appid_name = {i["appid"]:i["name"] for i in newApplist}
        additionalDoc = [{"appid":i,"name":appid_name[i]} for i in addtionalAppids]
        if len(additionalDoc) == 0:
            return
        self.db.appList.insert_many(additionalDoc)
        print("add AppList below...")
        print("total app count: %d"%self.db.appList.count())

    def __getGameDetailMapper(self,x):
        try:
            return x.json()[list(x.json().keys())[0]]["data"]
        except:
            return
    def getAppDetails(self):
        curAppidsSet = set(self.getAppids())
        updatedDetailsSet = set(self.db.appDetail.distinct('steam_appid'))
        ids2Add = curAppidsSet - updatedDetailsSet
        for idsChunk in list(self.chunks(list(ids2Add), 5)):
            myresponse,httpstatus = self.asyncRequest(reqUrl=self.G_URL,urlParams=None,targetArr=idsChunk)
            time.sleep(2)
            appDetails_ = map(lambda x: self.__getGameDetailMapper(x),myresponse)
            appDetails = [i for i in appDetails_ if i != None]
            yield appDetails


    def updateAppDetail(self):
        for appDetails in self.getAppDetails():
            lengthRslt = len(appDetails)
            if lengthRslt == 0:
                print("zero app Data")
                continue
            self.db.appDetail.insert_many(appDetails)
            print("insert %d app details"%lengthRslt)




    def getTopSellerAppIds(self):
        def appIdMapper(i):
            if i == None:
                return []
            return list(map(lambda x:int(x),i.split(",")))
        for idx in range(1,74):
            res = requests.get(self.topSellerList_URL%(idx))
            restxt = res.text
            soup = BeautifulSoup(restxt,"html.parser")
            rslt = soup.find_all("a",{"class":"search_result_row"})
            appids = []
            for rslt_i in rslt:
                try:
                    for id_i in appIdMapper(rslt_i.attrs['data-ds-appid']):
                        appids.append(id_i)
                except:
                    continue
            yield appids

    def updateAppDetail2(self):
        #curAppidsSet = set(self.getAppids())
        #updatedDetailsSet = set(self.db.appDetail.distinct('steam_appid'))
        #ids2Add = curAppidsSet - updatedDetailsSet
        updatedDetailsSet = set(self.db.appDetail.distinct('steam_appid'))
        for aid_arr in self.getTopSellerAppIds():
            print(aid_arr)
            if len(aid_arr) == 0:
                continue
            
            for aid in list(set(aid_arr) - updatedDetailsSet):
                failCnt = 0
                while True:
                    res = requests.get(self.G_URL%(aid))
                    time.sleep(1)
                    myAppDetail = self.__getGameDetailMapper(res)
                    if myAppDetail == None:
                        print("get app detail fail")
                        failCnt += 1
                        if failCnt == 5:
                            break
                        continue
                    print("insert app Detail %d"%aid)
                    self.db.appDetail.insert(myAppDetail)
                    break


   


    def updateAllAppReviews(self):
        appids = self.getAppids()
        for i in appids:
            self.updateAppReviews(i)
            print("appid %d, insert job is complete"%i)
        return


    def reqReviewList(self,appid,rng):
        rs_a,httpstatus = self.asyncRequest(reqUrl= self.R_URL,urlParams=[appid],targetArr= rng)
        res = [j for i in rs_a if i.json() != None for j in i.json()['reviews']]
        for res_i in res:
            try:
                res_i.update({"appid":appid})
                self.authors.add(res_i['author']['steamid'])
            except:
                continue
        return res

    def getAllReviews(self,appid):
        return self.db.appReview.find({"appid":appid})

    def updateAppReviews(self,appid):
        self.proxySetting()
        self.currentAppId = appid
        failCnt = 0
        insufficientCnt = 0
        if self.db.appReview.count({"appid":appid}) == 0:
            print("inserting reviews first time")
            n = 0
            while failCnt < 10:
                rng = range(n,(n+1)+80,20)
                res = self.reqReviewList(appid,rng)
                if len(res) == 0:
                    failCnt += 1
                    continue
                elif len(res) < 100:
                    print("insufficient data")
                    insufficientCnt += 1
                    if insufficientCnt < 10:
                        continue
                n = rng[-1]
                failCnt = 0
                insufficientCnt = 0
                self.db.appReview.insert_many(res)
                print("now adding appid:%d, total review size %d"%(appid,self.db.appReview.count()))

        else:
            print("insert additional reviews")
            lastUpdatedDt = self.db.appReview.find({"appid":appid}).sort('timestamp_created',-1)[0]['timestamp_created']
            n = 0
            isEnd = False
            inTheEnd = False
            while not isEnd:
                rng = range(n,(n+1)+80,20)
                res = self.reqReviewList(appid,rng)
                if len(res) == 0:
                    failCnt += 1
                    continue
                elif len(res) < 100:
                    print("insufficient data")
                    insufficientCnt += 1
                    if insufficientCnt < 10:
                        continue

                n = rng[-1]
                failCnt = 0
                insufficientCnt = 0

                m = len(res) -1

                while True:
                    if m < 0 :
                        isEnd = True
                        break
                    if res[m]['timestamp_created'] > lastUpdatedDt:
                        print(res[m]['timestamp_created'],lastUpdatedDt)
                        self.db.appReview.insert_many(res[:m+1])
                        if inTheEnd:
                            isEnd =True
                        break
                    else:
                        m -= 1
                        inTheEnd = True

        print("insert complete total review of AppID: %d is %d"%(appid,self.db.appReview.count({"appid":appid})))
        f = open("reviewUsers.txt","w")
        for i in list(self.authors):
            f.write(str(i)+"\n")
        f.close()
        f = open("appid.txt","w")
        f.write(str(self.currentAppId)+"\n")
        f.close()
        self.updateUserInfos()
        self.authors.clear()
        return


    def getUserSummary(self,userlist):
        res_,httpstatus = self.asyncRequest(reqUrl= self.U_URL,urlParams=[self.APIKEY],targetArr= userlist)
        docs = []
        for i,steamid_i in zip(res_,userlist):
            try:
                doc = i.json()["response"]['players'][0]
            except:
                continue
            docs.append(doc)
        return docs


    def getUserOwns(self,userlist):
        res_,httpstatus = self.asyncRequest(reqUrl= self.UO_URL,urlParams=[self.APIKEY],targetArr= userlist)
        docs = []
        for i,steamid_i in zip(res_,userlist):
            try:
                doc = i.json()["response"]
                _ = doc['game_count']
            except:
                continue
            doc.update({"steamid":steamid_i})
            docs.append(doc)
        return docs


    def getUserAchieve(self,userlist):
        res_,httpstatus = self.asyncRequest(reqUrl= self.UA_URL,urlParams=[self.currentAppId,self.APIKEY],targetArr= userlist)
        docs = []
        for i,steamid_i in zip(res_,userlist):
            try:
                doc = i.json()["playerstats"]
            except:
                continue
            doc.update({"appid":self.currentAppId})
            docs.append(doc)
        return docs


    def getUserBan(self,userlist):
        res_,httpstatus = self.asyncRequest(reqUrl= self.UB_URL,urlParams=[self.APIKEY],targetArr= userlist)

        docs = []

        for i,steamid_i in zip(res_,userlist):
            try:
                doc = i.json()["players"][0]
            except:
                continue
            doc.update({"appid":self.currentAppId})
            docs.append(doc)
        return docs

    def chunks(self,l, n):
        for i in range(0, len(l), n):
            yield l[i:i + n]

    def replaceUserCollection(self,dataArr,func,updateKeys):
        keysList = list(updateKeys.keys())
        for data in dataArr:
            try:
                func({myKey:data[myKey] for myKey in keysList},data)
            except:
                pass

    def updateUserInfos(self):
        insertFuncArr = [self.db.userSummary.insert_many,self.db.userOwns.insert_many,self.db.userAchieve.insert_many,self.db.userBan.insert_many]
        replaceFuncArr = [self.db.userSummary.replace_one,self.db.userOwns.replace_one,self.db.userAchieve.replace_one,self.db.userBan.replace_one]
        updateKeys = [{"steamid":-1},{"steamid":-1},{"steamID":-1,"appid":self.currentAppId},{"SteamId":-1,"appid":self.currentAppId}]
        users_inDB = set(self.db.userSummary.distinct("steamid"))
        newUsers = self.authors - users_inDB
        replaceUser = users_inDB & self.authors

        newUsersC = list(self.chunks(list(newUsers), self.chunksize))
        replaceUserC = list(self.chunks(list(replaceUser), self.chunksize))
        self.proxySetting()
        for taskflag,userChunks,funcArr in [("insert",newUsersC,insertFuncArr)] :
            for userlist in userChunks:
                us = self.getUserSummary(userlist) # pk : steamid
                uo = self.getUserOwns(userlist)    # pk : steamid
                ua = self.getUserAchieve(userlist) # pk : steamid + appid
                ub = self.getUserBan(userlist)     # pk : SteamId + appid
                for dataArr,func,updateKey in zip([us,uo,ua,ub],funcArr,updateKeys):
                    if len(dataArr) == 0:
                        continue
                    if taskflag == "insert":
                        func(dataArr)
                    else:
                        self.replaceUserCollection(dataArr,func,updateKey)
                print("userSummary Size %d"%self.db.userSummary.count())
                print("userOwns    Size %d"%self.db.userOwns.count())
                print("userAchieve Size %d"%self.db.userAchieve.count())
                print("userBan     Size %d"%self.db.userBan.count())

        return ;

    def updateUserOwns(self):
        insertFunc = self.db.userOwns.insert_many
        replaceFunc = self.db.userOwns.replace_one
        updateKey = {"steamid":-1}
        users_inDB = set(self.db.userOwns.distinct("steamid"))
        newUsers = self.authors - users_inDB
        replaceUser = users_inDB & self.authors
        newUsersC = list(self.chunks(list(newUsers), self.chunksize))
        for userlist in newUsersC:
            uo = self.getUserOwns(userlist)
            if len(uo) == 0:
                continue
            insertFunc(uo)
            print("userOwns    Size %d"%self.db.userOwns.count())
    
    def friendOffriend(self):
        users_inDB = set(self.db.userOwns.distinct("steamid"))
        newUsersC = list(self.chunks(list(users_inDB), self.chunksize))
        newFriends = []
        for userlist in newUsersC:
            res_,httpstatus = self.asyncRequest(reqUrl= self.UF_URL,urlParams=[self.APIKEY],targetArr= userlist)
            for i in res_:
                try:
                    newFriends_ = list(map(lambda x:x['steamid'],i.json()['friendslist']['friends']))
                except:
                    continue
                newFriends += newFriends_
        self.authors = set(newFriends)
        self.updateUserOwns()

def main():
    steamdata = SteamData()
    steamdata.updateAppReviews(578080)
            
