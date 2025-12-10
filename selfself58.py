# coding: utf-8
import os, sys, time, logging, json, re, asyncio
from datetime import datetime
import discord
from colorama import Fore, init
init(autoreset=True)

# ====== CONFIG ======
TOKEN = "MTM4MDE0MjA4NTU3ODk0ODYzMQ.GJEFIr.76fkgpshbVNaJ5XmMVplhcBZejmu1KW6MlnuH4"
SOURCE_CHANNELS = [1269240865243795498, 1396816819045531688]
BYPASS_CHANNEL_ID = 1442758029207539796
SERVICE_BOT_ID = 1415109094527860850
STATS_FILE = "stats.json"
BLACKLIST_FILE = "blacklist.json"
RESTART_TIMES_FILE = "restart_times.json"
AUTHORIZED_USER_ID = 1359497676432867389
TIMEOUT = 120
MAX_CONCURRENT = 3
RESTART_WINDOW = 60
RESTART_THRESHOLD = 5
# minimal supported list (keep your previous list if desired)
# minimal supported list (keep your previous list if desired)
SUPPORTED = [
    "admaven", "bit.do", "bit.ly", "blox-script", "boost-ink", "bst.gg", "bstlar", "bstshrt",
    "cl.gy", "codex", "pandadevelopment.net", "cuttlinks", "cuty", "delta", "getpolsec", "goo.gl",
    "is.gd", "keyguardian", "krnl", "ldnesfspublic", "link-hub.net", "link-unlock", "link4m.com",
    "link4sub", "linkify", "linkvertise", "linkunlocker", "lockr", "loot", "mboost", "mediafire",
    "nirbytes", "nicuse", "getkey", "overdrivehub", "paster.so", "paste-drop", "pastebin", "pastefy",
    "pastes.io", "platoboost", "quartyz", "rebrand.ly", "rekonise", "rinku.pro", "scriptpastebins",
    "shorter.me", "socialwolvez", "sub2get", "sub2unlock", "sub4unlock", "subfinal", "subnise",
    "t.co", "t.ly", "tpi.li", "trigon", "tiny.cc", "tinylink.onl", "tinyurl.com", "vaultlab", "v.gd", "ytsubme"
]
# ====== STATE ======
client = discord.Client()
pending_queue = []
active_tasks = {}
user_tasks = {}
stats = {"total":0,"success":0,"errors":0,"time":0.0,"avg":0.0}
user_stats = {}
BLACKLIST = ["luarmor","work.ink"]
ACCEPT_LINKS = True
SHUTDOWN_AFTER_QUEUE = False
RESTARTING = False
start_time = datetime.now()
active_count = 0

# ====== IO ======
def load():
    global stats, user_stats, BLACKLIST
    try:
        d=json.load(open(STATS_FILE,"r")); stats=d.get("global",stats); user_stats=d.get("users",{})
    except: pass
    try:
        bl=json.load(open(BLACKLIST_FILE,"r"))
        if isinstance(bl,list): BLACKLIST=bl
    except: pass

def save():
    try: json.dump({"global":stats,"users":user_stats}, open(STATS_FILE,"w"), indent=2)
    except: pass

def save_blacklist():
    try: json.dump(BLACKLIST, open(BLACKLIST_FILE,"w"), indent=2)
    except: pass

# ====== RESTART ======
def _record_restart_timestamp():
    now=time.time()
    try: arr=json.load(open(RESTART_TIMES_FILE,"r"))
    except: arr=[]
    arr=[t for t in arr if now-t<RESTART_WINDOW]; arr.append(now)
    try: json.dump(arr, open(RESTART_TIMES_FILE,"w"))
    except: pass
    return len(arr)

async def _do_restart(reason="manual"):
    global RESTARTING
    if RESTARTING: 
        print("[RESTART] already restarting")
        return
    RESTARTING=True
    print(f"[RESTART] requested: {reason}")
    try: save(); save_blacklist()
    except: pass
    pending_queue.clear(); active_tasks.clear(); user_tasks.clear()
    c=_record_restart_timestamp(); print(f"[RESTART] attempts in last {RESTART_WINDOW}s: {c}")
    if c>RESTART_THRESHOLD:
        print("[RESTART] too many restarts - aborting"); RESTARTING=False; return
    # do not wait on client.close() to avoid hangs (Termux issues), just execv or exit
    try:
        await asyncio.sleep(0.2)
    except: pass
    python=sys.executable
    try:
        print(f"[RESTART] execv -> {python} {' '.join(sys.argv)}")
        os.execv(python,[python]+sys.argv)
    except Exception as e:
        print(f"[RESTART] execv failed: {e}; fallback os._exit(1)")
        try: os._exit(1)
        except: raise

async def _do_shutdown(reason="shutdown"):
    try: save(); save_blacklist()
    except: pass
    pending_queue.clear(); active_tasks.clear(); user_tasks.clear()
    try: await client.close()
    except: pass
    try: os._exit(0)
    except: raise

# ====== LOG HANDLER ======
class DiscordLogHandler(logging.Handler):
    def emit(self, record):
        try: msg=record.getMessage()
        except: msg=str(record)
        ml=msg.lower()
        triggers=["can't keep up","you are being rate limited","429","rate limited","websocket is"]
        if any(t in ml for t in triggers):
            try:
                loop=None
                try: loop=asyncio.get_running_loop()
                except RuntimeError:
                    try: loop=asyncio.get_event_loop()
                    except: loop=None
                if loop and loop.is_running():
                    try: asyncio.run_coroutine_threadsafe(_do_restart(f"log trigger: {msg[:120]}"), loop)
                    except Exception as e: print("[LOGHANDLER] run_coroutine_threadsafe failed",e)
                else:
                    print("[LOGHANDLER] no running loop to schedule restart")
            except Exception as e:
                print("[LOGHANDLER] schedule failed",e)

# ====== UTIL ======
def supported(url):
    u=url.lower()
    if any(b in u for b in BLACKLIST): return False
    return any(s in u for s in SUPPORTED)

def fmt(sec):
    return f"{int(sec)}s" if sec<60 else f"{int(sec//60)}m {int(sec%60)}s"

def update_user_stats(user,success=True):
    uid=str(user.id)
    if uid not in user_stats: user_stats[uid]={"name":str(user),"total":0,"success":0,"errors":0}
    user_stats[uid]["total"]+=1
    if success: user_stats[uid]["success"]+=1
    else: user_stats[uid]["errors"]+=1

def extract_result(embed):
    if not embed: return None
    for f in getattr(embed,"fields",[]):
        if f.name and "result" in f.name.lower():
            r=f.value.strip().strip('`').strip()
            if r and len(r)>10: return r
    desc=getattr(embed,"description","") or ""
    for b in re.findall(r'```(.*?)```',desc,re.DOTALL):
        b=b.strip(); 
        if b and len(b)>10: return b
    return None

# ====== TASKS ======
async def process_task(task):
    global active_count
    task["start"]=datetime.now()
    task["status"]="processing"
    ch=client.get_channel(BYPASS_CHANNEL_ID)
    try:
        sent=await ch.send(task["url"])
        task["sent_id"]=sent.id; active_tasks[sent.id]=task; active_count+=1; user_tasks[str(task['user'].id)]=task
        try: await task["msg"].edit(content=f"{task['user'].mention} ⚡ processing\nuse `,status` to check")
        except: pass
        print(f"{Fore.GREEN}[SENT] ID:{sent.id} {task['user']} (active:{active_count})")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] {e}")
        active_count=max(0,active_count-1)
        task["status"]="error"

async def queue_worker():
    global active_count
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            while pending_queue and active_count<MAX_CONCURRENT:
                task=pending_queue.pop(0)
                asyncio.create_task(process_task(task))
                await asyncio.sleep(1)
        except Exception as e:
            print("[QUEUE] ",e)
        await asyncio.sleep(2)

async def monitor_tasks():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            for sid,task in list(active_tasks.items()):
                if task.get("status")!="processing": continue
                elapsed=(datetime.now()-task["start"]).total_seconds()
                if elapsed>TIMEOUT:
                    task["status"]="timeout"
                    try: await task["msg"].edit(content=f"{task['user'].mention} ⏰ timeout after {fmt(elapsed)}")
                    except: pass
                    stats["errors"]=stats.get("errors",0)+1; update_user_stats(task['user'],False); save()
                    del active_tasks[sid]; uid=str(task['user'].id)
                    if uid in user_tasks: del user_tasks[uid]
                    active_count=max(0,active_count-1)
            if SHUTDOWN_AFTER_QUEUE and not pending_queue and not active_tasks and active_count==0:
                asyncio.create_task(_do_shutdown("safeoff completed")); return
        except Exception as e:
            print("[MONITOR]",e)
        await asyncio.sleep(5)

# ====== EVENTS ======
@client.event
async def on_ready():
    load()
    try:
        lg=logging.getLogger("discord"); lg.setLevel(logging.WARNING); lg.addHandler(DiscordLogHandler())
    except Exception as e:
        print("[on_ready] log handler attach failed",e)
    print(f"\nBot ready: {client.user}; blacklist: {BLACKLIST}; success:{stats.get('success',0)}")
    client.loop.create_task(queue_worker()); client.loop.create_task(monitor_tasks())

@client.event
async def on_disconnect():
    print("[EVENT] on_disconnect — scheduling restart")
    try:
        loop=None
        try: loop=asyncio.get_running_loop()
        except RuntimeError:
            try: loop=asyncio.get_event_loop()
            except: loop=None
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(_do_restart("on_disconnect"), loop)
        else:
            try: asyncio.create_task(_do_restart("on_disconnect"))
            except Exception as e: print("[on_disconnect] schedule failed",e)
    except Exception as e:
        print("[on_disconnect] error",e)

@client.event
async def on_message(msg):
    global ACCEPT_LINKS, SHUTDOWN_AFTER_QUEUE
    if msg.author==client.user: return

    # admin commands
    if msg.author.id==AUTHORIZED_USER_ID:
        content=msg.content.strip()
        if content.lower().startswith(",restart"):
            await msg.channel.send("⚙️ Restarting (admin)..."); 
            try:
                loop=None
                try: loop=asyncio.get_running_loop()
                except RuntimeError:
                    try: loop=asyncio.get_event_loop()
                    except: loop=None
                if loop and loop.is_running(): asyncio.run_coroutine_threadsafe(_do_restart("manual by admin"), loop)
                else: asyncio.create_task(_do_restart("manual by admin"))
            except Exception as e: await msg.channel.send(f"❌ Failed to schedule restart: {e}")
            return
        if content.lower().startswith(",blacklist"):
            parts=content.split(None,1)
            if len(parts)<2: await msg.channel.send("Usage: `,blacklist <site>`"); return
            site=re.sub(r"^https?://","",parts[1].strip().lower()).split("/")[0]
            if site in BLACKLIST: await msg.channel.send(f"`{site}` déjà blacklisté")
            else: BLACKLIST.append(site); save_blacklist(); await msg.channel.send(f"✅ `{site}` ajouté"); print("[ADMIN] blacklisted",site)
            return
        if content.lower().startswith(",safeoff"):
            ACCEPT_LINKS=False; SHUTDOWN_AFTER_QUEUE=True
            await msg.channel.send("🔒 Safe-off activé — je traiterai la queue puis je m'arrêterai.")
            return

    # public commands
    if msg.content==",stats":
        uptime=fmt((datetime.now()-start_time).total_seconds())
        rate=(stats.get("success",0)/stats.get("total",0)*100) if stats.get("total",0)>0 else 0
        await msg.channel.send(f"**stats** ✅{stats.get('success',0)} ❌{stats.get('errors',0)} rate:{rate:.1f}% active:{active_count}/{MAX_CONCURRENT} queued:{len(pending_queue)} uptime:{uptime}")
        return
    if msg.content in (",status",",s"):
        uid=str(msg.author.id)
        if uid in user_tasks:
            t=user_tasks[uid]
            if t.get("result"): await msg.channel.send(f"{msg.author.mention} ✅ `{t['result']}`")
            else:
                st=t.get("status","queued")
                if st=="processing": await msg.channel.send(f"{msg.author.mention} ⚡ processing for {fmt((datetime.now()-t['start']).total_seconds())}")
                else: await msg.channel.send(f"{msg.author.mention} {st}")
        else:
            pos=None
            for i,t in enumerate(pending_queue):
                if str(t['user'].id)==uid: pos=i+1; break
            if pos: await msg.channel.send(f"{msg.author.mention} position {pos}/{len(pending_queue)}")
            else: await msg.channel.send(f"{msg.author.mention} no active bypass")
        return

    # auto-bypass submission
    if msg.channel.id in SOURCE_CHANNELS:
        if not ACCEPT_LINKS:
            await msg.channel.send(f"{msg.author.mention} 🔒 Bot n'accepte plus de nouveaux liens.")
            return
        urls=[w.strip("<>") for w in msg.content.split() if w.startswith(("http://","https://"))]
        if not urls: return
        for url in urls:
            if not supported(url):
                if any(b in url.lower() for b in BLACKLIST):
                    await msg.channel.send(f"{msg.author.mention} 🚫 blocked domain")
                else:
                    await msg.channel.send(f"{msg.author.mention} ❌ not supported")
                continue
            status_msg = await msg.channel.send(f"{msg.author.mention} queued — use `,status`")
            task={"user":msg.author,"url":url,"msg":status_msg,"retry":0,"start":None,"result":None,"status":"queued"}
            pending_queue.append(task); stats["total"]=stats.get("total",0)+1; save()
            print(f"[QUEUED] {msg.author} {url[:60]}")

@client.event
async def on_message_edit(before, after):
    global active_count
    if after.channel.id!=BYPASS_CHANNEL_ID or after.author.id!=SERVICE_BOT_ID or not after.reference: return
    sent_id=after.reference.message_id
    if sent_id not in active_tasks: return
    task=active_tasks[sent_id]
    if not after.embeds: return
    embed=after.embeds[0]; title=(embed.title or "").lower(); desc=(embed.description or "").lower()
    if "bypassing" in title or "bypassing" in desc: return
    if any(k in title for k in ("failed","error","not supported")):
        task["status"]="failed"
        try: await task["msg"].edit(content=f"{task['user'].mention} ❌ failed")
        except: pass
        stats["errors"]=stats.get("errors",0)+1; update_user_stats(task['user'],False); save()
        del active_tasks[sent_id]; uid=str(task['user'].id)
        if uid in user_tasks: del user_tasks[uid]
        active_count=max(0,active_count-1); return
    if any(k in title for k in ("success","bypassed")):
        res=extract_result(embed)
        if res:
            elapsed=(datetime.now()-task["start"]).total_seconds() if task.get("start") else 0
            task["result"]=res; task["status"]="completed"
            try: await task["msg"].edit(content=f"{task['user'].mention} ✅ done in {fmt(elapsed)}\n`{res}`")
            except: pass
            stats["success"]=stats.get("success",0)+1; stats["time"]=stats.get("time",0)+elapsed
            stats["avg"]=stats["time"]/stats["success"] if stats.get("success",0)>0 else 0
            update_user_stats(task['user'],True); save()
            del active_tasks[sent_id]; active_count=max(0,active_count-1)
        else:
            print("[ERROR] No result extracted")

# ====== RUN ======
if __name__=="__main__":
    try:
        client.run(TOKEN)
    except KeyboardInterrupt:
        try: save(); save_blacklist()
        except: pass
    except Exception as e:
        try: save(); save_blacklist()
        except: pass
        raise
