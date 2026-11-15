from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class EncodedSample:
    data: bytes
    frames: int
    book: tuple
    order: int = 2
    predictors: int = 1

    def __post_init__(self):
        if self.order != 2 or not 1 <= self.predictors <= 8 or len(self.book) != 16*self.predictors:
            raise ValueError('Invalid N64 predictor book dimensions')
        if any(not isinstance(n,(int,np.integer)) or not -32768 <= n <= 32767 for n in self.book):
            raise ValueError('Book coefficients must be signed int16')
        if not isinstance(self.frames,(int,np.integer)) or self.frames < 0 or len(self.data) != ((self.frames+15)//16)*9:
            raise ValueError('ADPCM storage does not match its PCM endpoint')
        if any((header >> 4)>12 or (header&15)>=self.predictors for header in self.data[::9]):
            raise ValueError('Invalid ADPCM scale or predictor')


def _clamp16(value):
    return min(32767,max(-32768,value))


def _decode_frame(data,table,previous):
    scale=data[0]>>4
    residuals=[]
    for byte in data[1:]:
        for nibble in (byte>>4,byte&15):
            residuals.append((nibble if nibble<8 else nibble-16)<<scale)
    result=[]
    prev2,prev1=previous
    for group in (residuals[:8],residuals[8:]):
        for j,residual in enumerate(group):
            acc=int(table[j])*prev2+int(table[8+j])*prev1+(residual<<11)
            for k in range(j):
                acc+=int(table[8+j-k-1])*group[k]
            acc=((acc+0x80000000)&0xFFFFFFFF)-0x80000000
            result.append(_clamp16(acc>>11))
        prev2,prev1=result[-2:]
    return result


def decode(sample):
    if not sample.data:
        return np.empty(0,dtype=np.int16)
    if not any(sample.book):
        frames=np.frombuffer(sample.data,dtype=np.uint8).reshape(-1,9)
        residuals=np.empty((len(frames),16),dtype=np.int32)
        residuals[:,::2]=frames[:,1:]>>4
        residuals[:,1::2]=frames[:,1:]&15
        residuals=np.where(residuals<8,residuals,residuals-16)
        return (residuals*(1<<(frames[:,0].astype(np.int32)>>4))[:,None]).reshape(-1)[:sample.frames].astype(np.int16)
    result=[]
    previous=(0,0)
    for offset in range(0,len(sample.data),9):
        frame=sample.data[offset:offset+9]
        index=(frame[0]&15)*16
        decoded=_decode_frame(frame,sample.book[index:index+16],previous)
        result.extend(decoded)
        previous=decoded[-2:]
    return np.asarray(result[:sample.frames],dtype=np.int16)


def loop_state(sample,start_frame):
    if not isinstance(start_frame,(int,np.integer)) or start_frame<0 or start_frame%16 or start_frame+16>sample.frames:
        raise ValueError('Loop start must select a complete aligned 16-sample block')
    return tuple(int(value) for value in decode(sample)[start_frame:start_frame+16])


def encode(pcm):
    pcm=np.asarray(pcm)
    if pcm.ndim!=1 or pcm.dtype.kind!='i' or pcm.dtype.itemsize!=2:
        raise ValueError('PCM must be a one-dimensional signed int16 array')
    count=len(pcm)
    book=(0,)*16
    if not count:
        return EncodedSample(b'',0,book)
    padded=np.pad(pcm.astype(np.int64),(0,(-count)%16)).reshape(-1,16)
    best_error=np.full(len(padded),np.iinfo(np.int64).max,dtype=np.int64)
    best_scale=np.zeros(len(padded),dtype=np.uint8)
    best_nibbles=np.zeros_like(padded,dtype=np.uint8)
    for scale in range(13):
        step=1<<scale
        quantized=np.clip((padded+step//2)//step,-8,7)
        error=np.sum((padded-quantized*step)**2,axis=1)
        better=error<best_error
        best_error[better]=error[better]
        best_scale[better]=scale
        best_nibbles[better]=quantized[better]&15
    packed=np.empty((len(padded),9),dtype=np.uint8)
    packed[:,0]=best_scale<<4
    packed[:,1:]=(best_nibbles[:,::2]<<4)|best_nibbles[:,1::2]
    return EncodedSample(packed.tobytes(),count,book)
