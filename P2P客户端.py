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
类型_获取UUID=0x09

# 打洞范围
打洞次数 = 500

# 探测包或会话保持包
探测标识 = "okgo"

# 网络信息
服务器IP = "penxia.dpdns.org"
服务器端口 = 3336


class 运行类:
    def __init__(self,目标_uuid):
        self.目标_uuid = 目标_uuid #对端uuid
        self.对端信息 = { #对端信息
            "uuid": "",  #多余,但不着急管,空闲再重构
            "ip": "",
            "port": -1
        }
        self.uuid = None #自己的uuid
        self.打洞成功 = False #打洞是否成功
        #打洞管理
        self.打洞线程计数 = 0
        self.打洞线程列表 = []
        self._打洞锁 = Lock()

        self.接收处理线程 = None #处理打洞的线程
        self.服务器会话线程 = None #请求交换信息的线程
        self.客户端会话线程=None #心跳
        #套接字
        self.套接字 = socket(AF_INET, SOCK_DGRAM)
        self.套接字.setsockopt(SOL_SOCKET, SO_RCVBUF, 1<<20)
        self.套接字.bind(("", 0))

        self.uuid初始化()#uuid初始化
        #启动工作线程
        self.服务器会话线程 = Thread(target=self.服务器会话,daemon=True)
        self.接收处理线程 = Thread(target=self.接收处理,daemon=True)
        self.服务器会话线程.start()
        self.接收处理线程.start()
        self.接收处理线程.join() #这个线程结束就说明打洞完成或失败了


    def uuid初始化(self):
        print("uuid初始化")
        while True:
            self.套接字.sendto(struct.pack(头部格式, 类型_获取UUID, b"", b"", False), (服务器IP, 服务器端口)) #uuid可以在本地创建,但当时脑抽让去服务器要了
            try:
                数据, 地址 = self.套接字.recvfrom(1024)
            except:
                time.sleep(1)
                continue
            self.uuid = UUID(bytes=数据)
            print(self.uuid)
            break


    def 服务器会话(self):
        print("服务器会话")
        while not self.打洞成功: #打洞完成不再请求
            self.套接字.sendto(struct.pack(头部格式,类型_P2P,self.uuid.bytes,self.目标_uuid.bytes,False), (服务器IP, 服务器端口))
            time.sleep(1)
        self.套接字.sendto(struct.pack(头部格式, 类型_关闭, self.uuid.bytes, self.目标_uuid.bytes, False),(服务器IP, 服务器端口))
        time.sleep(0.1)
        self.套接字.sendto(struct.pack(头部格式, 类型_关闭, self.uuid.bytes, self.目标_uuid.bytes, False),(服务器IP, 服务器端口)) #暂时解决丢包问题,但不完全
        print("打洞成功")


    def 接收处理(self):
        print("接收处理")
        while not self.打洞成功:
            try:
                self.套接字.setblocking(True)
                数据, 地址 = self.套接字.recvfrom(1024)
                数据 = 数据.decode("utf-8")
                if 数据=="no": #服务器找不到打洞对象的注册会返回
                    print("打洞失败")
                    quit()
                头部 = 数据.split("&")[0]
                uuid = UUID(数据.split("&")[1])
                if 头部 == 探测标识:  # 探测头,表示对方客户端找到你了
                    self.对端信息["uuid"] = uuid
                    self.对端信息["ip"] = 地址[0]
                    self.对端信息["port"] = 地址[1]
                    头部 = struct.pack(">BIIHH16s", 类型_P2P, 0, 0, 0, 0 ,self.uuid.bytes) #这里是因为服务端需要持续接受打洞,共用recvfrom需要格式化头,有机会会想办法
                    数据块 = f"{探测标识}&{self.uuid}&".encode("utf-8")
                    数据包 = 头部 + 数据块
                    self.套接字.sendto(数据包, 地址)#及时回应对方客户端,让对方知道打洞成功
                    self.打洞成功 = True #打洞成功状态
                    self.客户端会话线程 = Thread(target=self.客户端会话) #心跳线程
                    self.客户端会话线程.start()
                    time.sleep(0.5)
                    self.清理UDP缓冲区() #清理延迟到的包

                elif 头部 == "server_ok":  # 服务器消息头,对端数据交换
                    if 数据.split("&")[2]=="{}": #第一次请求,对端还来不及响应,会回个空的
                        continue
                    try:
                        信息 = json.loads(数据.split("&")[2])
                    except:
                        continue
                    字典={"uuid":uuid,"ip":信息["ip"],"port":信息["port"]}
                    if self.打洞线程计数 >= 5:  #控制打洞线程数量
                        # 更新对方客户端信息
                        self.对端信息 = 字典

                    elif self.打洞线程计数 < 5:
                        # 更新对方客户端信息
                        self.对端信息 = 字典
                        # 创建端口轰炸线程
                        t = Thread(target=self.开始打洞)
                        with self._打洞锁:
                            self.打洞线程列表.append(t)
                        t.start()
            except Exception as e:
                traceback.print_exc()


    def 客户端会话(self):
        while True:
            self.套接字.sendto(探测标识.encode("utf-8"), (self.对端信息["ip"], self.对端信息["port"]))
            time.sleep(9)


    def 开始打洞(self):
        print(f"开始打洞{self.打洞线程计数}")
        try:
            self.打洞线程计数 += 1  # 开始一个线程数量＋1
            for i in range(打洞次数):
                time.sleep(0.006)
                if self.打洞成功:
                    break
                头部=struct.pack(">BIIHH16s",类型_P2P,0,0,0,0,self.uuid.bytes)
                数据块=f"{探测标识}&{self.uuid}&".encode("utf-8")
                数据包=头部+数据块
                self.套接字.sendto(数据包, (self.对端信息["ip"], self.对端信息["port"] + i))
        finally:
            # 无论如何都要安全地更新状态和移除线程引用
            with self._打洞锁:
                self.打洞线程计数 -= 1
                try:
                    self.打洞线程列表.remove(current_thread())
                except:pass


    def 清理UDP缓冲区(self):
        self.套接字.setblocking(False)  # 非阻塞模式
        try:
            while True:
                self.套接字.recvfrom(65535)  # 把所有缓存里的包读出来丢掉
        except BlockingIOError:
            pass  # 没包可读就跳出
        finally:
            self.套接字.setblocking(True)  # 记得恢复阻塞模式