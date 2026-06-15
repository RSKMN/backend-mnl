import asyncio
import sys
import os
from pathlib import Path

async def test():
    try:
        cmd = [sys.executable, "-c", "print('hello')"]
        q_ai_drug_dir = Path("E:/rskmn/Npersonal/quinfosys/drug_discovery_research/work/mnl/q-ai-drug-new")
        
        env = os.environ.copy()
        env["PYTHONPATH"] = str(q_ai_drug_dir / "src") + os.pathsep + env.get("PYTHONPATH", "")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(q_ai_drug_dir) if q_ai_drug_dir.exists() else None,
            env=env
        )
        out, err = await process.communicate()
        print("OUT:", out)
        print("ERR:", err)
        print("RC:", process.returncode)
    except Exception as e:
        print("EXCEPTION:", repr(e))

if __name__ == "__main__":
    asyncio.run(test())
