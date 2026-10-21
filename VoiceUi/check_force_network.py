"""真机启动前核验本机 UDP 绑定地址，不向机器人发送数据。"""
import ipaddress
import socket
import sys


def validate_local_address(value: str) -> None:
    """要求明确的单播 IPv4，并使用系统 UDP bind 检查地址归属。"""
    address = ipaddress.IPv4Address(value)
    if address.is_unspecified or address.is_loopback or address.is_multicast or address.is_reserved:
        raise ValueError("请填写连接机器人网卡的实际 IPv4 地址")
    # 端口由系统临时分配；只绑定本机，不连接、发包或修改网卡配置。
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind((str(address), 0))


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("用法：check_force_network.py LOCAL_IP", file=sys.stderr)
        return 2
    try:
        validate_local_address(args[0])
    except (OSError, ValueError) as error:
        print(f"启动已取消：本机 IP {args[0]!r} 无法用于实时 UDP 绑定：{error}", file=sys.stderr)
        print("请用 ip -br -4 addr 核对有线网卡地址，再修改启动命令的第二个 IP。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
