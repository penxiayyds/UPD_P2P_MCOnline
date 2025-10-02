# 服务端代理.py
import time
from collections import OrderedDict
import socket
import threading
import struct
import traceback
import P2P服务端

探测标识=P2P服务端.探测标识.encode("utf-8")
p2p实例=P2P服务端.运行类()

# 配置（按需修改）
MC服务器地址 = ('127.0.0.1', 25565)  # 真实 Minecraft 服务器地址

头部格式 = ">BIIHH16s"
头部大小 = struct.calcsize(头部格式)
类型_MC = 0x01
类型_确认   = 0x02
类型_关闭 = 0x05
类型_P2P=0x10

最大负载 = 1024  # 保守一点，避免超过UDP上限
连接字典 = {}
待确认包   = {}
分片数据 = {} #标记,只增不减,短时间内存泄漏不重不影响使用,后续再做处理
消息ID字典={}
已完成消息 = OrderedDict()
连接锁 = threading.Lock()
消息锁 = threading.Lock()

def 发送分片数据(连接ID, 数据,地址,uuid):
    """分片并发送，每个分片要求确认，超时重发"""
    with 消息锁:
        消息ID = 消息ID字典[(连接ID,uuid)]
        消息ID字典[(连接ID,uuid)]= 消息ID+1
    总数 = (len(数据) + 最大负载 - 1) // 最大负载
    for 序号 in range(总数):
        数据块 = 数据[序号*最大负载:(序号+1)*最大负载]
        头部 = struct.pack(头部格式, 类型_MC, 连接ID, 消息ID, 序号, 总数,uuid)
        数据包 = 头部 + 数据块
        with 消息锁:
            待确认包[(连接ID,消息ID, 序号 ,uuid)] = (数据包, 地址, time.time())
        p2p实例.套接字.sendto(数据包, 地址)


def 重发循环():
    """定时重发未确认分片"""
    while True:
        当前时间 = time.time()
        with 消息锁:
            for 键, (数据包,地址, 最后发送时间) in list(待确认包.items()):
                if 当前时间 - 最后发送时间 > 0.1:  # 100ms 超时
                    p2p实例.套接字.sendto(数据包, 地址)
                    待确认包[键] = (数据包, 当前时间)
                    print(键)
        time.sleep(0.05)


def tcp到本地循环(连接ID, tcp套接字, udp地址,uuid):
    消息ID字典[(连接ID,uuid)]=1
    print()
    """从真实 MC 服务器读数据，发回客户端代理的 UDP（带连接ID）"""
    try:
        while True:
            数据 = tcp套接字.recv(65536)
            if not 数据:
                # 后端断开，通知客户端并清理
                p2p实例.套接字.sendto(struct.pack(头部格式, 类型_关闭, 连接ID, 0, 0, 0,uuid), udp地址)
                break
            发送分片数据(连接ID, 数据, udp地址, uuid)
    except :pass
    finally:
        try:
            tcp套接字.close()
        except: pass
        with 连接锁:
            连接字典.pop((连接ID,uuid), None)
            消息ID字典.pop((连接ID,uuid), None)
        print(f"conn_id: {连接ID} 关闭")



def udp接收循环():
    """接收来自客户端的 UDP 包并路由到对应的后端 TCP"""
    while True:
        try:
            数据, 来源地址 = p2p实例.套接字.recvfrom(60000)
            if not 数据 or len(数据) < 头部大小 or 数据==探测标识:
                try:
                    if type(eval(数据.decode("utf-8")))==type(1):
                        p2p实例.重新注册服务器(数据)
                except:pass
                continue
            类型, 连接ID,消息ID,序号,总数,uuid = struct.unpack(头部格式, 数据[:头部大小])
            负载 = 数据[头部大小:]
            if 类型 == 类型_MC:
                with 连接锁:
                    信息 = 连接字典.get((连接ID,uuid))

                if 信息 is None:
                    # 新连接：创建到 MC 后端的 TCP 连接，并保存 udp 源地址用于回复
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        s.connect(MC服务器地址)
                        with 连接锁:
                            连接字典[(连接ID,uuid)] = {'tcp': s, 'udp_addr': 来源地址}
                        threading.Thread(target=tcp到本地循环, args=(连接ID, s, 来源地址, uuid), daemon=True).start()
                        print(f"[中继] 为 conn {连接ID} 建立到 MC 后端的 TCP 连接")
                    except Exception as e:
                        print(f"[中继] 无法连接 MC 后端: {e}")
                        # 通知客户端断开
                        p2p实例.套接字.sendto(struct.pack(头部格式, 类型_关闭, 连接ID, 0, 0, 0,uuid), 来源地址)
                        continue
                    信息 = 连接字典.get((连接ID,uuid))
                # 分片拼接
                if (连接ID, 消息ID,uuid) in 已完成消息:
                    # 已完成的消息：仍然回确认，但不再处理
                    确认包 = struct.pack(头部格式, 类型_确认, 连接ID, 消息ID, 序号, 总数,uuid)
                    p2p实例.套接字.sendto(确认包, 来源地址)
                    continue
                # 发确认
                确认包 = struct.pack(头部格式, 类型_确认, 连接ID, 消息ID, 序号, 总数,uuid)
                p2p实例.套接字.sendto(确认包, 来源地址)
                缓冲区 = 分片数据.setdefault((连接ID, 消息ID,uuid), {})
                缓冲区[序号] = 负载
                if len(缓冲区) == 总数 and all(i in 缓冲区 for i in range(总数)): #分片集齐,开始拼接
                    组装数据 = b''.join(缓冲区[i] for i in range(总数))
                    分片数据.pop((连接ID, 消息ID,uuid), None)
                    标记完成((连接ID, 消息ID, uuid))
                    try:
                        信息['tcp'].sendall(组装数据)
                    except Exception:
                        traceback.print_exc()
                        try:
                            信息['tcp'].close()
                        except:pass
                        with 连接锁:
                            连接字典.pop((连接ID,uuid), None)
                        p2p实例.套接字.sendto(struct.pack(头部格式, 类型_关闭, 连接ID, 0, 0, 0,uuid), 来源地址)

            elif 类型 == 类型_关闭:
                # 客户端告知关闭，关闭后端 TCP
                with 连接锁:
                    信息 = 连接字典.pop((连接ID,uuid))
                if 信息:
                    try:
                        信息['tcp'].close()
                    except: pass
                print(f"conn_id: {连接ID} 关闭")

            elif 类型==类型_P2P:
                p2p实例.接收处理(负载,来源地址)

            elif 类型 == 类型_确认:
                with 消息锁:
                    if (连接ID, 消息ID, 序号 ,uuid) in 待确认包:
                        del 待确认包[(连接ID, 消息ID, 序号, uuid)]
        except Exception:
            pass
            # print("udp_recv_loop接收接收到 ICMP Unreachable")


def 标记完成(消息ID):
    已完成消息[消息ID] = time.time()
    已完成消息.move_to_end(消息ID)

def 清理循环():
    """定期清理过期已完成消息，但保留最后一个"""
    while True:
        当前时间 = time.time()
        键列表 = list(已完成消息.keys())
        for k in 键列表[:-1]:  # 保留最后一个
            if 当前时间 - 已完成消息[k] > 30:
                del 已完成消息[k]
        time.sleep(5)

if __name__ == "__main__":
    print("[中继] 启动服务端代理")
    threading.Thread(target=重发循环, daemon=True).start()
    threading.Thread(target=清理循环, daemon=True).start()
    udp接收循环()
