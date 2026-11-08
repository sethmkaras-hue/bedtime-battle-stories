"""Compatibility entry point for the current mobile adventure regression."""
import sys
from redesign_smoke import run
if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8502')
