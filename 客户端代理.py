# 客户端代理.py
from collections import OrderedDict
import socket
import threading
import struct
import time
import traceback
from uuid import UUID, uuid4
import P2P客户端

探测标识=P2P客户端.探测标识.encode("utf-8")
p2p实例=P2P客户端.运行类(UUID("d1585c38-8f6f-4ff6-96ee-97eb3b413619")) #d2931b0f-5d6e-47c7-81ba-db969476ad7f  #8c091f4d-482f-4489-8d0e-8cdc59c27aeb
if not p2p实例.打洞成功:
    quit()

# 配置（按需修改）
本地TCP绑定 = ('0.0.0.0', 25566)   # Minecraft 客户端连到这里
中继UDP地址 = (p2p实例.对端信息["ip"],p2p实例.对端信息["port"]) # 中继服务的 UDP 地址

头部格式 = ">BIIHH16s"  # type(1) + conn_id(4) + seq(2) + last_flag(1)
头部大小 = struct.calcsize(头部格式)

类型_MC = 0x01
类型_确认   = 0x02
类型_关闭 = 0x05

最大负载 = 1024  # 保守一点，避免超过UDP上限

tcp监听器 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
tcp监听器.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
tcp监听器.bind(本地TCP绑定)
tcp监听器.listen(10)

连接字典 = {}
待确认包   = {}
分片数据 = {}
消息ID字典={}
已完成消息 = OrderedDict()
连接锁 = threading.Lock()
消息锁 = threading.Lock()
接收锁 = threading.Lock()

_下一个连接ID = 1


def 发送分片数据(连接ID, 数据,uuid):
    """把大数据分片后通过UDP发送"""
    with 消息锁:
        消息ID=消息ID字典[(连接ID,uuid)]
        消息ID字典[(连接ID,uuid)] = 消息ID+1
    总数 = (len(数据)+最大负载-1) // 最大负载
    for 序号 in range(0, 总数):
        数据块 = 数据[序号*最大负载:(序号+1)*最大负载]
        头部 = struct.pack(头部格式, 类型_MC, 连接ID, 消息ID, 序号, 总数,uuid)
        数据包 = 头部 + 数据块
        with 消息锁:
            待确认包[(连接ID, 消息ID, 序号 ,uuid)] = (数据包, time.time())
        p2p实例.套接字.sendto(数据包, 中继UDP地址)


def 重发循环():
    """定时重发未确认分片"""
    while True:
        当前时间 = time.time()
        with 消息锁:
            for 键, (数据包, 最后发送时间) in list(待确认包.items()):
                if 当前时间 - 最后发送时间 > 0.1:  # 100ms 超时
                    p2p实例.套接字.sendto(数据包, 中继UDP地址)
                    待确认包[键] = (数据包, 当前时间)
        time.sleep(0.05)


def 生成连接ID():
    global _下一个连接ID
    with 连接锁:
        连接ID = _下一个连接ID
        _下一个连接ID = (_下一个连接ID + 1) & 0xFFFFFFFF
        if _下一个连接ID == 0:
            _下一个连接ID = 1
        return 连接ID


def udp接收循环():
    """统一接收来自中继服务的 UDP，按连接ID分发到对应TCP socket"""
    while True:
        try:
            with 接收锁:
                数据, 地址 = p2p实例.套接字.recvfrom(60000)
            if not 数据 or len(数据) < 头部大小 or 数据==探测标识:
                continue
            类型, 连接ID,消息ID,序号,总数,uuid = struct.unpack(头部格式, 数据[:头部大小])
            负载 = 数据[头部大小:]
            with 连接锁:
                套接字 = 连接字典.get((连接ID,uuid))
            if 类型 == 类型_MC:
                if 套接字:
                    if (连接ID,消息ID,uuid) in 已完成消息:
                        # 已完成的消息：仍然回确认，但不再处理
                        确认包 = struct.pack(头部格式, 类型_确认, 连接ID, 消息ID, 序号, 总数,uuid)
                        p2p实例.套接字.sendto(确认包, 地址)
                        continue
                    # 发确认
                    确认包 = struct.pack(头部格式, 类型_确认, 连接ID, 消息ID, 序号, 总数,uuid)
                    p2p实例.套接字.sendto(确认包, 地址)
                    缓冲区 = 分片数据.setdefault((连接ID,消息ID,uuid), {})
                    缓冲区[序号] = 负载
                    if len(缓冲区) == 总数 and all(i in 缓冲区 for i in range(总数)): #分片集齐,开始拼接
                        组装数据 = b''.join(缓冲区[i] for i in range(总数))
                        分片数据.pop((连接ID,消息ID,uuid), None)
                        标记完成((连接ID,消息ID,uuid))
                        try:
                            套接字.sendall(组装数据)
                        except Exception:
                            # 发送失败 -> 关闭该连接
                            try:
                                套接字.close()
                            except: pass
                            with 连接锁:
                                连接字典.pop((连接ID,uuid), None)
                else:
                    print(f"没有找到 {连接ID} 的MC连接")

            elif 类型 == 类型_关闭:
                # 中继告知后端关闭
                if 套接字:
                    try:
                        套接字.close()
                    except: pass
                    with 连接锁:
                        连接字典.pop((连接ID,uuid), None)
                    print(f"[本地] 收到关闭请求 for conn {连接ID}, 已关闭本地 TCP")

            elif 类型 == 类型_确认:
                with 消息锁:
                    if (连接ID, 消息ID, 序号 ,uuid) in 待确认包:
                        del 待确认包[(连接ID, 消息ID, 序号, uuid)]
        except Exception:
            traceback.print_exc()


def 标记完成(消息ID):
    已完成消息[消息ID] = time.time()
    已完成消息.move_to_end(消息ID)


def 处理客户端(连接套接字, 客户端地址, 连接ID, uuid):
    消息ID字典[(连接ID,uuid)] = 1
    """从 TCP 客户端读数据，发到中继服务（UDP）"""
    print(f"[本地] 新客户端 {客户端地址} -> conn_id {连接ID}")
    try:
        while True:
            数据 = 连接套接字.recv(65536)
            if not 数据:
                # 客户端关闭，通知中继关闭后端连接
                p2p实例.套接字.sendto(struct.pack(头部格式, 类型_关闭, 连接ID, 0, 0, 0,uuid), 中继UDP地址)
                break
            发送分片数据(连接ID, 数据,uuid)
    except:pass
    finally:
        try:
            连接套接字.close()
        except: pass
        with 连接锁:
            连接字典.pop((连接ID,uuid), None)
            消息ID字典.pop((连接ID,uuid),None)
        print(f"conn_id: {连接ID} 关闭")


def 接受循环():
    uuid=p2p实例.uuid.bytes
    while True:
        套接字, 地址 = tcp监听器.accept()
        连接ID = 生成连接ID()
        with 连接锁:
            连接字典[(连接ID,uuid)] = 套接字
        t = threading.Thread(target=处理客户端, args=(套接字, 地址, 连接ID, uuid), daemon=True)
        t.start()

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
    print("[本地] 启动客户端代理")
    threading.Thread(target=重发循环, daemon=True).start()
    for i in range(10):
        threading.Thread(target=udp接收循环, daemon=True).start()
    threading.Thread(target=清理循环, daemon=True).start()
    接受循环()
