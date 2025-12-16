## uart-tool

自用uart-tool，适用于字符串/16 进制log 读取

## support commands

### uart-tool

```shell
uart-tool -h
usage: uart-tool [-h] -p COM_PORT [-b BAURATE] [-t TIMEOUT] [--hex_mode] [--print_str] [--test_mode] [-e END]

uart tool 参数

options:
  -h, --help            show this help message and exit
  -p COM_PORT, --com_port COM_PORT
                        COM 串口名字
  -b BAURATE, --baurate BAURATE
                        COM 口波特率配置,默认115200
  -t TIMEOUT, --timeout TIMEOUT
                        COM 读写消息间隔,默认0.1
  --hex_mode            是否使用16进制模式
  --print_str           是否打印字符串模式
  --test_mode           是否进入测试模式
  -e END, --end END     换行字符\r或者\n
```

### lsuart

列出当前系统的串口