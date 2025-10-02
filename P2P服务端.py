import traceback
from socket import *
from threading import *
import json
import time
import struct
from uuid import UUID

头部格式=">B16s16s?"
类型_P2P=0x10
类型_关闭=0x03
类型_注销=0x07
类型_获取UUID=0x09

# 打洞范围
打洞次数 = 500

# 探测包或会话保持包
探测标识 = "okgo"

# 网络信息
服务器IP = "penxia.dpdns.org"
服务器端口 = 3336


class 运行类:
    def __init__(self):
        self.uuid=None
        self.已注册=False
        self.对端信息 = {}
        self.打洞成功 = False #打洞是否成功
        self.打洞线程计数 = 0

        self.服务器会话线程 = None
        self.客户端会话线程=None
        self._打洞锁 = Lock()
        self.打洞线程列表 = []
        self.套接字 = socket(AF_INET, SOCK_DGRAM)
        self.套接字.setsockopt(SOL_SOCKET, SO_RCVBUF, 1<<20)
        self.套接字.bind(("", 0))
        self.uuid初始化()
        self.注册服务器()
        self.唤醒线程=Thread(target=self.唤醒)
        self.唤醒线程.start()
        self.客户端会话线程 = Thread(target=self.客户端会话)
        self.客户端会话线程.start()


    def uuid初始化(self):
        while True:
            self.套接字.sendto(struct.pack(头部格式, 类型_获取UUID, b"", b"", False), (服务器IP, 服务器端口))
            try:
                数据, 地址 = self.套接字.recvfrom(1024)
            except:
                time.sleep(1)
                continue
            self.uuid = UUID(bytes=数据)
            print(f"uuid初始化{self.uuid}")
            break


    def 注册服务器(self):
        print("开始注册")
        while True:
            数据包=struct.pack(头部格式,类型_P2P,self.uuid.bytes,b"",True)
            self.套接字.sendto(数据包,(服务器IP,服务器端口))
            try:
                数据,地址=self.套接字.recvfrom(1024)
            except Exception:
                traceback.print_exc()
                time.sleep(1)
                print("注册失败,开始重试")
                continue
            端口=eval(数据.decode("utf-8"))
            self.tcp=socket(AF_INET, SOCK_STREAM)
            self.tcp.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
            time.sleep(1)
            try:
                self.tcp.connect((服务器IP,端口))
            except Exception:
                traceback.print_exc()
                self.套接字.sendto(struct.pack(头部格式,类型_注销,self.uuid.bytes,b"",False), (服务器IP,服务器端口))
                time.sleep(1)
                print(f"注册失败,端口:{端口}错误")
                continue
            print("注册成功")
            break


    def 重新注册服务器(self,数据):
        print("重新注册")
        端口 = eval(data.decode("utf-8"))
        self.tcp = socket(AF_INET, SOCK_STREAM)
        self.tcp.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
        try:
            self.tcp.connect((服务器IP, 端口))
        except Exception:
            traceback.print_exc()
            self.套接字.sendto(struct.pack(头部格式, 类型_注销, self.uuid.bytes, b"", False),(服务器IP, 服务器端口))
            print(f"注册失败,端口:{端口}错误")
            return
        print("注册成功")


    def 唤醒(self):
        print("唤醒服务")
        while True:
            time.sleep(1)
            try:
                self.tcp.settimeout(60) #发现tcp连接会莫名其妙断开而不知,设置重注册机制刷新连接
                数据=self.tcp.recv(1024)
                if len(数据)>3:
                    uuid=UUID(bytes=数据)
                    print(f"{uuid} 发起打洞")
                    self.打洞成功=False
                    self.套接字.sendto(struct.pack(头部格式,类型_P2P,self.uuid.bytes,uuid.bytes,False), (服务器IP, 服务器端口)) #及时回复
                    Thread(target=self.服务器会话,args=(uuid,)).start()
                elif 数据==b"":
                    self.套接字.sendto(struct.pack(头部格式, 类型_注销, self.uuid.bytes, b"", False),(服务器IP, 服务器端口))
                    print("tcp连接关闭,发送注销请求")
                    self.套接字.sendto(struct.pack(头部格式, 类型_P2P, self.uuid.bytes, b"", True),(服务器IP, 服务器端口))  # 发起新注册,回应会通过处理mc数据的recvfrom处理
                    try:
                        self.tcp.close()
                    except:pass
                    time.sleep(3)
            except:
                self.套接字.sendto(struct.pack(头部格式, 类型_注销, self.uuid.bytes, b"", False),(服务器IP, 服务器端口))
                print("tcp连接关闭,发送注销请求")
                self.套接字.sendto(struct.pack(头部格式, 类型_P2P, self.uuid.bytes, b"", True),(服务器IP, 服务器端口))  # 发起新注册,回应会通过处理mc数据的recvfrom处理
                time.sleep(3)


    def 服务器会话(self,uuid):
        print("服务器会话")
        while not self.打洞成功:
            self.套接字.sendto(struct.pack(头部格式,类型_P2P,self.uuid.bytes,uuid.bytes,False), (服务器IP, 服务器端口))
            time.sleep(1)  # 向服务器发送维持包
        self.套接字.sendto(struct.pack(头部格式, 类型_关闭, self.uuid.bytes, uuid.bytes, False),(服务器IP, 服务器端口))
        time.sleep(0.1)
        self.套接字.sendto(struct.pack(头部格式, 类型_关闭, self.uuid.bytes, uuid.bytes, False),(服务器IP, 服务器端口)) #暂时解决丢包问题,但不完全
        print("打洞成功")


    def 接收处理(self,数据,地址):
        if not self.打洞成功:
            try:
                数据 = 数据.decode("utf-8")
            except Exception:
                traceback.print_exc()
                return
            头部=数据.split("&")[0]
            uuid=UUID(数据.split("&")[1])
            if 头部 == "server_ok":  # 服务器消息头,对端数据交换
                try:
                    信息 = json.loads(数据.split("&")[2])
                except Exception:
                    traceback.print_exc()
                    return
                print(f"收到交换信息请求{数据}")
                if self.打洞线程计数 >= 5:  #控制打洞线程数量
                    # 更新对方客户端信息
                    self.对端信息[uuid] = 信息

                elif self.打洞线程计数 < 5:
                    # 更新对方客户端信息
                    self.对端信息[uuid] = 信息
                    # 创建端口轰炸线程
                    t = Thread(target=self.开始打洞,args=(uuid,))
                    with self._打洞锁:
                        self.打洞线程列表.append(t)
                    t.start()

            elif 头部 == 探测标识:
                self.对端信息[uuid]={ "ip": 地址[0], "port": 地址[1]}
                self.套接字.sendto(f"{探测标识}&{self.uuid}&".encode("utf-8"), 地址)
                self.打洞成功=True


    def 开始打洞(self,uuid):
        print(f"开始打洞{self.打洞线程计数}")
        try:
            self.打洞线程计数 += 1  # 开始一个线程数量＋1
            for i in range(打洞次数):
                time.sleep(0.006)
                if self.打洞成功:
                    break
                self.套接字.sendto(f"{探测标识}&{self.uuid}&".encode("utf-8"), (self.对端信息[uuid]["ip"], self.对端信息[uuid]["port"] + i))
        finally:
            # 无论如何都要安全地更新状态和移除线程引用
            with self._打洞锁:
                self.打洞线程计数 -= 1
                # 按对象移除，而不是 pop(0)
                try:
                    self.打洞线程列表.remove(current_thread())
                except:pass


    def 客户端会话(self):
        print("客户端会话")
        #会话保持,防止端口发生变化