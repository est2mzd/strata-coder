"""Process lifetime lock, shared by the stdio gateway and coordinator."""
def exclusive_lock(path):
    import os
    f=path.open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            f.write(b'0');f.flush();f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        f.close();raise RuntimeError('Another process owns '+str(path)) from None
    return f
