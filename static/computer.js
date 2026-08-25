(() => {
  async function act(agent, payload) {
    const response=await fetch(`/api/computers/${agent}/action`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    if(!response.ok){ const data=await response.json(); alert(data.error||'Computer action failed'); }
  }
  document.querySelectorAll('.interactive-screen').forEach(img=>img.addEventListener('click',event=>{
    const rect=img.getBoundingClientRect();
    const x=(event.clientX-rect.left)*(1280/rect.width), y=(event.clientY-rect.top)*(800/rect.height);
    act(img.dataset.agent,{action:'click',x,y});
  }));
  document.querySelectorAll('.human-type').forEach(button=>button.addEventListener('click',()=>{
    const input=document.querySelector(`.human-text[data-agent="${button.dataset.agent}"]`);
    act(button.dataset.agent,{action:'type',text:input.value}); input.value='';
  }));
  document.querySelectorAll('.human-enter').forEach(button=>button.addEventListener('click',()=>act(button.dataset.agent,{action:'key',key:'Enter'})));
})();
