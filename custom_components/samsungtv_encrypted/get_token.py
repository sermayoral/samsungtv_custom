import sys
import getopt

from PySmartCrypto.pysmartcrypto import PySmartCrypto

help_msg = '''
Usage: get_token.py [options]

Available options:

--ip, -i \tSmart TV IP address
--port, -p \tSmart TV port
-h \t\t Show this help message
'''


def main(argv):
    ip = ''
    port = ''
    try:
        opts, args = getopt.getopt(argv, "hi:p:", ["ip=", "port="])
    except getopt.GetoptError:
        print(help_msg)
        sys.exit(2)
    if len(opts) == 0:
        print(help_msg)
        sys.exit()
    for opt, arg in opts:
        if opt == '-h':
            print(help_msg)
            sys.exit()
        elif opt in ("-i", "--ip"):
            ip = arg
        elif opt in ("-p", "--port"):
            port = arg
    PySmartCrypto(ip, port)


if __name__ == "__main__":
    main(sys.argv[1:])
