#!/usr/bin/env python3
'''
Author: Vincent Young
Date: 2023-01-17 03:51:29
LastEditors: Vincent Young
LastEditTime: 2023-01-17 23:43:25
FilePath: /zzttDownloader/zztt.py
Telegram: https://t.me/missuo

Copyright © 2023 by Vincent, All Rights Reserved. 
'''
import httpx
from lxml import etree
import json
import os
import re
import sys
import queue
import base64
import platform
import requests
import urllib3
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.options import Options
import uuid

class ThreadPoolExecutorWithQueueSizeLimit(ThreadPoolExecutor):
    """
    实现多线程有界队列
    队列数为线程数的2倍
    """

    def __init__(self, max_workers=None, *args, **kwargs):
        super().__init__(max_workers, *args, **kwargs)
        self._work_queue = queue.Queue(max_workers * 2)


def make_sum():
    ts_num = 0
    while True:
        yield ts_num
        ts_num += 1


class M3u8Download:
    """
    :param url: 完整的m3u8文件链接 如"https://www.bilibili.com/example/index.m3u8"
    :param name: 保存m3u8的文件名 如"index"
    :param max_workers: 多线程最大线程数
    :param num_retries: 重试次数
    :param base64_key: base64编码的字符串
    """

    def __init__(self, url, name, max_workers=64, num_retries=5, base64_key=None):
        self._url = url
        self._name = name
        self._max_workers = max_workers
        self._num_retries = num_retries
        # self._file_path = file_path
        self._file_path = os.path.join(os.getcwd(), self._name)
        self._front_url = None
        self._ts_url_list = []
        self._success_sum = 0
        self._ts_sum = 0
        self._key = base64.b64decode(base64_key.encode()) if base64_key else None
        self._headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) \
        AppleWebKit/537.36 (KHTML, like Gecko) Chrome/84.0.4147.105 Safari/537.36'}

        urllib3.disable_warnings()

        self.get_m3u8_info(self._url, self._num_retries)
        print('Downloading: %s' % self._name, 'Save path: %s' % self._file_path, sep='\n')
        with ThreadPoolExecutorWithQueueSizeLimit(self._max_workers) as pool:
            for k, ts_url in enumerate(self._ts_url_list):
                pool.submit(self.download_ts, ts_url, os.path.join(self._file_path, str(k)), self._num_retries)
        if self._success_sum == self._ts_sum:
            self.output_mp4()
            self.delete_file()
            print(f"Download successfully --> {self._name}")

    def get_m3u8_info(self, m3u8_url, num_retries):
        """
        获取m3u8信息
        """
        try:
            with requests.get(m3u8_url, timeout=(3, 30), verify=False, headers=self._headers) as res:
                self._front_url = res.url.split(res.request.path_url)[0]
                if "EXT-X-STREAM-INF" in res.text:  # 判定为顶级M3U8文件
                    for line in res.text.split('\n'):
                        if "#" in line:
                            continue
                        elif line.startswith('http'):
                            self._url = line
                        elif line.startswith('/'):
                            self._url = self._front_url + line
                        else:
                            self._url = self._url.rsplit("/", 1)[0] + '/' + line
                    self.get_m3u8_info(self._url, self._num_retries)
                else:
                    m3u8_text_str = res.text
                    self.get_ts_url(m3u8_text_str)
        except Exception as e:
            print(e)
            if num_retries > 0:
                self.get_m3u8_info(m3u8_url, num_retries - 1)

    def get_ts_url(self, m3u8_text_str):
        """
        获取每一个ts文件的链接
        """
        if not os.path.exists(self._file_path):
            os.mkdir(self._file_path)
        new_m3u8_str = ''
        ts = make_sum()
        for line in m3u8_text_str.split('\n'):
            if "#" in line:
                if "EXT-X-KEY" in line and "URI=" in line:
                    if os.path.exists(os.path.join(self._file_path, 'key')):
                        continue
                    key = self.download_key(line, 5)
                    if key:
                        new_m3u8_str += f'{key}\n'
                        continue
                new_m3u8_str += f'{line}\n'
                if "EXT-X-ENDLIST" in line:
                    break
            else:
                if line.startswith('http'):
                    self._ts_url_list.append(line)
                elif line.startswith('/'):
                    self._ts_url_list.append(self._front_url + line)
                else:
                    self._ts_url_list.append(self._url.rsplit("/", 1)[0] + '/' + line)
                new_m3u8_str += (os.path.join(self._file_path, str(next(ts))) + '\n')
        self._ts_sum = next(ts)
        with open(self._file_path + '.m3u8', "wb") as f:
            if platform.system() == 'Windows':
                f.write(new_m3u8_str.encode('gbk'))
            else:
                f.write(new_m3u8_str.encode('utf-8'))

    def download_ts(self, ts_url, name, num_retries):
        """
        下载 .ts 文件
        """
        ts_url = ts_url.split('\n')[0]
        try:
            if not os.path.exists(name):
                with requests.get(ts_url, stream=True, timeout=(5, 60), verify=False, headers=self._headers) as res:
                    if res.status_code == 200:
                        with open(name, "wb") as ts:
                            for chunk in res.iter_content(chunk_size=1024):
                                if chunk:
                                    ts.write(chunk)
                        self._success_sum += 1
                        sys.stdout.write('\r[%-25s](%d/%d)' % ("*" * (100 * self._success_sum // self._ts_sum // 4),
                                                               self._success_sum, self._ts_sum))
                        sys.stdout.flush()
                    else:
                        self.download_ts(ts_url, name, num_retries - 1)
            else:
                self._success_sum += 1
        except Exception:
            if os.path.exists(name):
                os.remove(name)
            if num_retries > 0:
                self.download_ts(ts_url, name, num_retries - 1)

    def download_key(self, key_line, num_retries):
        """
        下载key文件
        """
        mid_part = re.search(r"URI=[\'|\"].*?[\'|\"]", key_line).group()
        may_key_url = mid_part[5:-1]
        if self._key:
            with open(os.path.join(self._file_path, 'key'), 'wb') as f:
                f.write(self._key)
            return f'{key_line.split(mid_part)[0]}URI="./{self._name}/key"'
        if may_key_url.startswith('http'):
            true_key_url = may_key_url
        elif may_key_url.startswith('/'):
            true_key_url = self._front_url + may_key_url
        else:
            true_key_url = self._url.rsplit("/", 1)[0] + '/' + may_key_url
        try:
            with requests.get(true_key_url, timeout=(5, 30), verify=False, headers=self._headers) as res:
                with open(os.path.join(self._file_path, 'key'), 'wb') as f:
                    f.write(res.content)
            return f'{key_line.split(mid_part)[0]}URI="./{self._name}/key"{key_line.split(mid_part)[-1]}'
        except Exception as e:
            print(e)
            if os.path.exists(os.path.join(self._file_path, 'key')):
                os.remove(os.path.join(self._file_path, 'key'))
            print("加密视频,无法加载key,揭秘失败")
            if num_retries > 0:
                self.download_key(key_line, num_retries - 1)

    def output_mp4(self):
        """
        合并.ts文件，输出mp4格式视频，需要ffmpeg
        """
        cmd = f"ffmpeg -allowed_extensions ALL -i '{self._file_path}.m3u8' -acodec \
        copy -vcodec copy -f mp4 '{self._file_path}.mp4'"
        os.system(cmd)

    def delete_file(self):
        file = os.listdir(self._file_path)
        for item in file:
            os.remove(os.path.join(self._file_path, item))
        os.removedirs(self._file_path)
        os.remove(self._file_path + '.m3u8')


def decode_image(src):
    """
    解码图片
    :param src: 图片编码
        eg:
            src="data:image/gif;base64,R0lGODlhMwAxAIAAAAAAAP///
                yH5BAAAAAAALAAAAAAzADEAAAK8jI+pBr0PowytzotTtbm/DTqQ6C3hGX
                ElcraA9jIr66ozVpM3nseUvYP1UEHF0FUUHkNJxhLZfEJNvol06tzwrgd
                LbXsFZYmSMPnHLB+zNJFbq15+SOf50+6rG7lKOjwV1ibGdhHYRVYVJ9Wn
                k2HWtLdIWMSH9lfyODZoZTb4xdnpxQSEF9oyOWIqp6gaI9pI1Qo7BijbF
                ZkoaAtEeiiLeKn72xM7vMZofJy8zJys2UxsCT3kO229LH1tXAAAOw=="

    :return: str 保存到本地的文件名
    """
    # 1、信息提取
    result = re.search("data:image/(?P<ext>.*?);base64,(?P<data>.*)", src, re.DOTALL)
    if result:
        ext = result.groupdict().get("ext")
        data = result.groupdict().get("data")

    else:
        raise Exception("Do not parse!")

    # 2、base64解码
    img = base64.urlsafe_b64decode(data)

    # 3、二进制文件保存
    filename = "{}.{}".format(uuid.uuid4(), ext)
    with open(filename, "wb") as f:
        f.write(img)

    return filename


def videoParse(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
    }
    r = httpx.get(url = url, headers = headers).text
    tree = etree.HTML(r)
    # Get all videos
    videos = tree.xpath('//*[@id="post"]/article/div[3]/div')
    videoNum = 1
    for video in videos:
        dataConfig = video.get('data-config')
        if dataConfig is not None:
            videoData = json.loads(dataConfig)
            videoUrl = videoData["video"]["url"]
            filename = os.path.basename(videoUrl).replace('.m3u8','')
            M3u8Download(videoUrl, filename, max_workers=64, num_retries=10)
            print(videoUrl)
        videoNum = videoNum + 1
    print("All videos have been downloaded!")

def imageParse(url):
    option = webdriver.ChromeOptions()
    option.add_argument("--headless")
    driver = webdriver.Chrome('./chromedriver', options=option)
    driver.get(url)
    imgs = driver.find_elements('xpath','//*[@id="post"]/article/div[3]/p/img')
    for img in imgs:
        imgBase64 = img.get_attribute('src')
        decode_image(imgBase64)
    print("All images have been downloaded!")

def main():
    postUrl = input("Paste post url here: ")
#   postUrl = "https://zztt31.com/archives/16161.html"
    imageParse(postUrl)
    videoParse(postUrl)

main()
    