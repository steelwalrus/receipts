"""A reentrant process/thread lock so restore cannot race local writes."""

import os
import threading
import time
from contextlib import contextmanager


class VaultLock:
    def __init__(self,path):
        self.path = path
        self.mutex = threading.RLock()
        self.depth = 0

    @contextmanager
    def hold(self):
        with self.mutex:
            handle = None
            if self.depth==0:
                handle = open(self.path,"a+b")
                handle.seek(0,os.SEEK_END)
                if handle.tell()==0:
                    handle.write(b"0")
                    handle.flush()
                deadline = time.monotonic()+20
                while True:
                    try:
                        handle.seek(0)
                        if os.name=="nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                        else:
                            import fcntl
                            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        break
                    except (OSError,BlockingIOError):
                        if time.monotonic()>deadline:
                            handle.close()
                            raise ValueError("Vault is busy with another operation. Try again shortly")
                        time.sleep(.05)
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1
                if handle:
                    handle.seek(0)
                    if os.name=="nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(handle,fcntl.LOCK_UN)
                    handle.close()
