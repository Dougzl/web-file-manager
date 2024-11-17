#file-browser

# 简介
```text
file-browser 是一个带有linux终端界面的文件管理系统，旨在解决一些内网服务器繁琐的操作流程，实现方便快捷的部署及命令发布。
但就安全性来说，file-browser是可能存在问题的，直接将服务暴露在浏览器端还是挺危险的操作，使用需慎重！！！
```

## 技术栈
```text
django + xterm.js + vue
```

# 打包编译
```shell
pyinstaller file-browser.spec --noconfirm

dist/file-browser/./file-browser runserver --noreload
```


# 添加 守护进程
```shell
vim /etc/systemd/system/file-browser.service

systemctl start file-browser.service
systemctl enable file-browser.service
```

## 界面展示


## 待完成
### 1. 客户端奔溃问题
### 2. 客户断连清除缓存
