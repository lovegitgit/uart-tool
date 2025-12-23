## uart-tool

自用uart-tool，适用于字符串/16 进制log 读取

## support commands

### uart-tool

```shell
uart-tool -h
usage: uart-tool [-h] -p COM_PORT [-b BAURATE] [-t TIMEOUT] [--hex_mode] [--print_str] [-e [END]]

uart tool 参数

optional arguments:
  -h, --help            show this help message and exit
  -p COM_PORT, --com_port COM_PORT
                        COM 串口名字
  -b BAURATE, --baurate BAURATE
                        COM 口波特率配置,默认115200
  -t TIMEOUT, --timeout TIMEOUT
                        COM 读写消息间隔,默认0.1
  --hex_mode            是否使用16进制模式
  --print_str           是否打印字符串模式
  -e [END], --end [END]
                        换行字符\r或者\n, 默认\r (使用 -e '' 或 -e 传空字符串表示不追加换行)
```

### lsuart

列出当前系统的串口
