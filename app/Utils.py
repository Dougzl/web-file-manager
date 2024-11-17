import json
import os
import shutil

from django.http import HttpResponse, Http404, FileResponse
from django.utils.encoding import escape_uri_path
from django.utils.deprecation import MiddlewareMixin
import tempfile, zipfile
from wsgiref.util import FileWrapper
from pathlib import Path
from datetime import datetime
from tempfile import NamedTemporaryFile

class Folder:
    def __init__(self, path):
        self.path = path

    def __getFolderDict(self, path):
        try:
            os.chdir(path)
            content = os.listdir(path)
            file = Path(path)
            file_creation_time = file.stat().st_ctime  # 获取创建时间
            creation_time_str = datetime.fromtimestamp(file_creation_time).strftime('%Y-%m-%d %H:%M:%S')

            currentDict = {"name": os.path.basename(path), "open": False, "path": path, "time": creation_time_str}
            children = []
            # 定义单位
            size_units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
            # 隐藏文件
            content = list(filter(lambda c: not c.startswith('.'), content))

            for i in content:
                if os.path.isdir(i):
                    cpath = path + "/" + i
                    file = Path(cpath)
                    file_creation_time = file.stat().st_ctime  # 获取创建时间
                    creation_time_str = datetime.fromtimestamp(file_creation_time).strftime('%Y-%m-%d %H:%M:%S')
                    children.append({"name": i, "path": cpath, "isParent": "true", "time": creation_time_str})
            for i in content:
                if not os.path.isdir(i):
                    cpath = path + "/" + i
                    file = Path(cpath)
                    file_creation_time = file.stat().st_ctime  # 获取创建时间
                    creation_time_str = datetime.fromtimestamp(file_creation_time).strftime('%Y-%m-%d %H:%M:%S')

                    size_in_bytes = file.stat().st_size
                    # 转换文件大小
                    size = size_in_bytes
                    unit_index = 0

                    while size >= 1024 and unit_index < len(size_units) - 1:
                        size /= 1024.0
                        unit_index += 1

                    children.append({"name": i, "path": cpath, "size": f"{size:.0f} {size_units[unit_index]}", "time": creation_time_str})
            currentDict["children"] = children
            return children
        except Exception as e:
            currentDict = {"name": os.path.basename(path)+" Error"+repr(e), "open": False, "path": path}
            return currentDict

    def getFolderJson(self):
        return json.dumps(self.__getFolderDict(self.path))


class fileOperator:
    def __init__(self, path=None):
        self.path = path

    def forceRemove(self, path):
        try:
            # if os.path.isfile(path):
            #     os.remove(path)
            #     return
            #
            # fileList=os.listdir(path)
            # for file in fileList:
            #     if os.path.isfile(path+"/"+file):
            #         os.remove(path+"/"+file)
            #     else:
            #         self.forceRemove(path+"/"+file)
            #
            # os.removedirs(path)
            if os.path.isfile(path):
                os.remove(path)
                return
            else:
                if len(os.listdir(path)) == 0:
                    os.rmdir(path)
                else:
                    shutil.rmtree(path)
                    os.rmdir(path)
        except:
            pass
        return

    def copyFiles(self, list, targetPath,isMove=False):
        copyedList=[]
        if not os.path.isdir(targetPath):
            targetPath=os.path.dirname(targetPath)
        for i in list:
            if os.path.exists(targetPath + '/' + os.path.basename(i)):
                temp = 0
                while True:
                    fname, ext = os.path.splitext(os.path.basename(i))
                    if not os.path.exists(targetPath + '/' + fname + str(temp) + ext):
                        shutil.copy(i, targetPath + '/' + fname + str(temp) + ext)
                        copyedList.append(i)
                        break
                    else:
                        temp += 1
            shutil.copy(i, targetPath + '/' + os.path.basename(i))
            copyedList.append(i)
        if isMove:
            for i in copyedList:
                os.remove(i)
        return True

    def zipFilesInResponse(self, downloadPath):
        if not os.path.isdir(downloadPath):
            try:
                response = FileResponse(open(downloadPath, 'rb'))
                response['content-type'] = "application/octet-stream"
                response['Content-Disposition'] = 'attachment;'
                response['filename'] = escape_uri_path((os.path.basename(downloadPath)))
                return response
            except Exception:
                raise Http404
        else:
            okList = []

            # 创建一个临时文件作为 zip 文件存储
            with NamedTemporaryFile(delete=False, suffix=".zip") as temp_zip_file:
                zipFile = zipfile.ZipFile(temp_zip_file, "w", zipfile.ZIP_DEFLATED)

                # 遍历并压缩目标文件夹
                for path, dirnames, filenames in os.walk(downloadPath):
                    fpath = path.replace(downloadPath, '')
                    for filename in filenames:
                        full_file_path = os.path.join(path, filename)
                        if full_file_path not in okList:
                            okList.append(full_file_path)
                            zipFile.write(full_file_path, os.path.join(fpath, filename))

                zipFile.close()  # 确保 zip 文件已关闭

            # 使用 FileResponse 并通过流式读取文件，减少内存占用
            response = FileResponse(open(temp_zip_file.name, 'rb'))
            response['content-type'] = "application/octet-stream"
            response['Content-Disposition'] = f'attachment; filename="{os.path.basename(temp_zip_file.name)}"'

            try:
                # 清理临时文件
                os.remove(temp_zip_file.name)
            except:
                pass
            return response
            # except Exception:
            #     raise Http404
            # finally:
            #     pass

    def mkdir(self,path):
        temp=0
        if os.path.isdir(path):
            if os.path.exists(path+"/newFolder"):
                while True:
                    if not os.path.exists(path+"/newFolder"+str(temp)):
                        os.mkdir(path+"/newFolder"+str(temp))
                        break
                    temp+=1
            else:
                os.mkdir(path + "/newFolder")

        else:
            if os.path.exists(os.path.dirname(path)+"/newFolder"):
                while True:
                    if not os.path.exists(os.path.dirname(path)+"/newFolder"+str(temp)):
                        os.mkdir(os.path.dirname(path)+"/newFolder"+str(temp))
                        break
                    temp+=1
            else:
                os.mkdir(os.path.dirname(path) + "/newFolder")



if __name__ == "__main__":
    test = fileOperator()
    test.forceRemove("/home/daiqiang/桌面/test")
