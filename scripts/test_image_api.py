"""测试图片上传和获取 API"""
import requests
import io
import json
import struct
import zlib

def create_test_png():
    """创建 1x1 白色 PNG"""
    def chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xffffffff)
        return struct.pack('>I', len(data)) + c + crc
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    raw = b'\x00\xff\xff\xff\x00\x00\x00'
    idat = zlib.compress(raw)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', idat) + chunk(b'IEND', b'')

# 测试上传
png_data = create_test_png()
files = [('images', ('test_upload.png', io.BytesIO(png_data), 'image/png'))]
data = {'project': 'test_project'}
resp = requests.post('http://localhost:8888/api/upload', files=files, data=data)
print('=== Upload Test ===')
print('Status:', resp.status_code)
print('Response:', json.dumps(resp.json(), ensure_ascii=False, indent=2))

if resp.ok:
    img_info = resp.json()['images'][0]
    img_url = f"http://localhost:8888{img_info['url']}"
    resp2 = requests.get(img_url)
    print('\n=== Serve Test ===')
    print('Status:', resp2.status_code)
    print('Content-Type:', resp2.headers.get('Content-Type'))
    print('Content-Length:', len(resp2.content))
    
    # 测试不支持的文件类型
    print('\n=== Validation Test (bad ext) ===')
    files_bad = [('images', ('test.txt', io.BytesIO(b'hello'), 'text/plain'))]
    resp_bad = requests.post('http://localhost:8888/api/upload', files=files_bad, data=data)
    print('Status:', resp_bad.status_code)
    print('Response:', resp_bad.text[:200])
    
    # 测试超大文件
    print('\n=== Validation Test (oversized) ===')
    big_data = b'\x00' * (11 * 1024 * 1024)  # 11MB
    files_big = [('images', ('big.png', io.BytesIO(big_data), 'image/png'))]
    resp_big = requests.post('http://localhost:8888/api/upload', files=files_big, data=data)
    print('Status:', resp_big.status_code)
    print('Response:', resp_big.text[:200])

print('\n=== All tests done ===')
