from socket import *
import json
import time
from threading import Thread
from uuid import uuid4,UUID
import struct
import traceback

类型_P2P=0x10
类型_关闭=0x03
类型_注销=0x07
类型_获取UUID=0x09

头部格式=">B16s16s?"

服务器连接={}
连接计数=0

class 服务器类:
    def __init__(self):
        self.会话计数 = 0
        self.IP = "0.0.0.0"
        self.端口 = 3336
        self.客户端1 = {
            "uuid": "",
            "ip": "",
            "port": -1
        }
        self.客户端2 = {
            "uuid": "",
            "ip": "",
            "port": -1
        }
        self.套接字 = socket(AF_INET, SOCK_DGRAM)
        self.套接字.bind((self.IP, self.端口))
        print("服务器启动")
        self.运行()

    def 运行(self):
        global 连接计数
        while True:
            try:
                数据, 地址 = self.套接字.recvfrom(1024)
            except:
                traceback.print_exc()
                continue
            类型,uuid1,uuid2,是否注册= struct.unpack(头部格式, 数据) #请求类型,自己uuid,要找uuid,是否注册
            uuid1=UUID(bytes=uuid1)
            uuid2=UUID(bytes=uuid2)
            if 类型==类型_关闭: #打洞完毕,清除会话
                self.客户端1={}
                self.客户端2={}
                self.会话计数=0
                print("清除会话")
                time.sleep(0.5)
                self.清理UDP缓冲区()
                continue
            elif 类型==类型_P2P: #P2P类请求
                if 是否注册: #注册新服务端槽位,仅注册
                    print(f"{uuid1}注册请求")
                    连接计数+=1
                    s=socket(AF_INET, SOCK_STREAM)
                    s.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
                    s.bind((self.IP, self.端口+连接计数))
                    s.listen(1)
                    Thread(target=self.注册,args=(uuid1,s)).start()
                    Thread(target=self.超时注销,args=(uuid1,)).start()
                    self.套接字.sendto(f"{self.端口+连接计数}".encode("utf-8"), 地址)

                elif self.会话计数==0: #没有人打洞,可以使用
                    print(f"{uuid1}向请求打洞{uuid2}")
                    self.会话计数=1
                    self.客户端1["uuid"]=uuid1
                    self.客户端1["ip"] = 地址[0]
                    self.客户端1["port"] = 地址[1]
                    if uuid2 in 服务器连接.keys(): #服务端存在,唤醒服务端
                        print("尝试唤醒")
                        服务器连接[uuid2].send(uuid1.bytes)
                        self.套接字.sendto(f"server_ok&{uuid2}&{json.dumps({})}".encode("utf-8"), 地址)
                        Thread(target=self.超时清除会话).start()
                    else: #服务端不存在,不打洞
                        print("请求的服务端不存在")
                        self.套接字.sendto("no".encode("utf-8"), 地址)
                        self.客户端1 = {}
                        self.会话计数 = 0
                        continue

                elif self.会话计数 == 1: #等待另一个人
                    if self.客户端1["uuid"] == uuid1: #是会话1自己,不做操作
                        self.套接字.sendto(f"server_ok&{uuid2}&{json.dumps({})}".encode("utf-8"), 地址)
                        print("是会话1自己,不做操作")
                    elif self.客户端1["uuid"] == uuid2: #服务端找会话1,回应
                        print("服务端找会话1")
                        self.客户端2["uuid"] = uuid1
                        self.客户端2["ip"] = 地址[0]
                        self.客户端2["port"] = 地址[1]
                        数据=json.dumps({"ip":self.客户端1["ip"],"port":self.客户端1["port"]})
                        uuid=self.客户端1["uuid"]
                        self.套接字.sendto(f"server_ok&{uuid}&{数据}".encode("utf-8"), 地址)
                        self.会话计数 = 2
                elif self.会话计数==2: #两个会话已开始工作,外人勿进
                    print("会话1的请求,回应会话2的信息")
                    if uuid1==self.客户端1["uuid"]: #会话1的请求,回应(会话2信息)
                        self.客户端1["port"] = 地址[1]
                        数据 = json.dumps({ "ip": self.客户端2["ip"], "port": self.客户端2["port"]})
                        uuid=self.客户端2["uuid"]
                        self.套接字.sendto(f"server_ok&{uuid}&{数据}".encode("utf-8"), 地址)
                    elif uuid1==self.客户端2["uuid"]: #会话2的请求,回应(会话1信息)
                        print("会话2的请求,回应会话1的信息")
                        self.客户端2["port"] = 地址[1]
                        数据 = json.dumps({"ip": self.客户端1["ip"], "port": self.客户端1["port"]})
                        uuid=self.客户端1["uuid"]
                        头部 = struct.pack(">BIIHH16s", 类型_P2P, 0, 0, 0, 0 ,uuid1.bytes)
                        数据块=f"server_ok&{uuid}&{数据}".encode("utf-8")
                        数据包=头部+数据块
                        self.套接字.sendto(数据包, 地址)

            elif 类型==类型_注销: #服务端注销请求
                try:
                    tcp = 服务器连接[uuid1]
                    tcp.close()
                    del 服务器连接[uuid1]
                except:pass
                连接计数-=1
                print(f"服务{uuid1}注销")

            elif 类型==类型_获取UUID: #获取uuid
                self.套接字.sendto(uuid4().bytes, 地址)
                print(地址,"请求uuid")


    def 注册(self,uuid,sock): #注册功能
        s,地址=sock.accept()
        服务器连接[uuid] = s
        print(f"服务{uuid}注册成功")


    def 清理UDP缓冲区(self):
        self.套接字.setblocking(False)  # 非阻塞模式
        try:
            while True:
                self.套接字.recvfrom(65535)  # 把所有缓存里的包读出来丢掉
        except BlockingIOError:
            pass  # 没包可读就跳出
        finally:
            self.套接字.setblocking(True)  # 记得恢复阻塞模式


    def 超时清除会话(self):
        time.sleep(20)
        print("会话清理")
        s=socket(AF_INET,SOCK_DGRAM)
        s.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 3340))
        s.sendto(struct.pack(头部格式, 类型_关闭, b"", b"", False),("127.0.0.1", 3336))


    def 超时注销(self,uuid):
        time.sleep(60)
        s = socket(AF_INET, SOCK_DGRAM)
        s.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 3341))
        s.sendto(struct.pack(头部格式, 类型_注销, uuid.bytes, b"", False), ("127.0.0.1", 3336))  # 暂时解决丢包问题,但不完全


if __name__ == "__main__":
    服务器= 服务器类()
    print("服务器停止运行")