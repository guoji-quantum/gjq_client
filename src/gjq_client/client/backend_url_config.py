import base64
import os
import hashlib

# 默认 API 基础地址（认证服务）
DEFAULT_BASE_URL = 'tUIBYIoaYiCfMdzah3vBMYMsTuE39mjS512YO11ZMUyF06gcSgh8lexe6UA='  #正式环境
#DEFAULT_BASE_URL = "c6awL498NDByfQG7uBLjHt3cRPWF2DYAR/pB/8pvxWJmW/tLQXy+"  #测试环境

# 默认后端查询 API 基础地址
DEFAULT_BACKEND_URL = 'tUIBYIoaYiCfMdzah3vBMYMsTuE39mjS512YO11ZMUyF06gcSgh8lexe6UA='  #正式环境
#DEFAULT_BACKEND_URL = "BlPeMMCchQfFtXRYknr803II30xSjbg9TSeDgO/92rT5R5N7U3ms"  #测试环境  


def xor_bytes(a: bytes, b: bytes) -> bytes:
    """对两个字节串进行按位异或操作，返回结果字节串。"""
    return bytes(x ^ y for x, y in zip(a, b))

def encrypt_url(secret_key: bytes, url: str) -> str:
    """
    加密 URL
    返回:
        base64(nonce + ciphertext)
    """

    nonce = os.urandom(12)
    plaintext = url.encode("utf-8")

    # 生成 keystream
    keystream = hashlib.shake_128(
        secret_key + nonce
    ).digest(len(plaintext))
    # XOR 加密
    ciphertext = xor_bytes(plaintext, keystream)
    # nonce + ciphertext
    final_data = nonce + ciphertext
    return base64.b64encode(final_data).decode("utf-8")


def decrypt_url(secret_key: bytes, encrypted_url: str) -> str:
    """
    解密 URL
    """
    data = base64.b64decode(encrypted_url)
    nonce = data[:12]
    ciphertext = data[12:]

    # 重新生成 keystream
    keystream = hashlib.shake_128(
        secret_key + nonce
    ).digest(len(ciphertext))
    # XOR 解密
    plaintext = xor_bytes(ciphertext, keystream)
    return plaintext.decode("utf-8")

if __name__ == "__main__":
    secret_key =b'test'
    decrypted = encrypt_url(secret_key, 'https://example.com/api')
    print(decrypted)