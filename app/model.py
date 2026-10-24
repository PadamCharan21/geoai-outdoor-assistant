import os, threading, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
_lock=threading.Lock(); _model=None; _tokenizer=None
def _load():
 global _model,_tokenizer
 if _model is not None:return
 with _lock:
  if _model is not None:return
  mid=os.getenv("MODEL_ID","Qwen/Qwen2.5-0.5B-Instruct")
  _tokenizer=AutoTokenizer.from_pretrained(mid)
  device=os.getenv("MODEL_DEVICE","auto")
  _model=AutoModelForCausalLM.from_pretrained(mid,torch_dtype="auto",device_map=device)
def explain(question:str, recommendation:dict)->str:
 """Ask the local SLM to summarize only evidence already computed by the app."""
 _load()
 prompt=("You are an outdoor activity assistant. Use only facts present in DATA. "
 "Do not invent venues, weather, travel times, or safety guarantees. If status says Avoid this window, clearly advise avoiding it. State the activity, place, best time, one or two evidence facts, and practical advice. Be concise.\n"
 f"QUESTION: {question}\nDATA: {recommendation}")
 msgs=[{"role":"user","content":prompt}]
 inp=_tokenizer.apply_chat_template(msgs,tokenize=True,add_generation_prompt=True,return_tensors="pt").to(_model.device)
 ids=_model.generate(inp,max_new_tokens=int(os.getenv("MODEL_MAX_NEW_TOKENS","150")),do_sample=False,pad_token_id=_tokenizer.eos_token_id)
 return _tokenizer.decode(ids[0][inp.shape[-1]:],skip_special_tokens=True).strip()

