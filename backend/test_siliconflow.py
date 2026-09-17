import os
from siliconflow import SiliconFlowAdapter

old=os.environ.pop("SILICONFLOW_API_KEY", None)
try:
    try: SiliconFlowAdapter().complete({"input":{}}, 0)
    except RuntimeError as e: assert str(e)=="SILICONFLOW_API_KEY_MISSING"
    else: raise AssertionError("missing key was not rejected")
finally:
    if old is not None: os.environ["SILICONFLOW_API_KEY"]=old
print("ok")
