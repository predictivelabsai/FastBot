(() => {
  const form = document.querySelector('#chat-form');
  if (!form) return;
  const messages = document.querySelector('#messages');
  const activity = document.querySelector('#activity');
  const composer = document.querySelector('#composer');
  const button = document.querySelector('#send-button');
  let bubble = null;

  function addMessage(role, text='') {
    const row = document.createElement('div'); row.className = `message ${role}`;
    const el = document.createElement('div'); el.className = 'bubble markdown'; el.textContent = text;
    row.appendChild(el); messages.appendChild(row); messages.scrollTop = messages.scrollHeight; return el;
  }
  function log(title, detail='') {
    const el = document.createElement('div'); el.className = 'activity-item';
    const strong = document.createElement('strong'); strong.textContent = title; el.appendChild(strong);
    if (detail) { const span = document.createElement('span'); span.textContent = detail; el.appendChild(span); }
    activity.prepend(el);
  }
  function renderUI(value) {
    if (!value) return;
    const card = document.createElement('div'); card.className = 'ui-card';
    const title = document.createElement('h4'); title.textContent = value.props.title || 'Checklist'; card.appendChild(title);
    if (value.component === 'checklist') (value.props.items || []).forEach(item => { const label = document.createElement('label'); const cb = document.createElement('input'); cb.type='checkbox'; label.append(cb, ` ${item}`); card.appendChild(label); });
    else if (value.component === 'metric') { const metric=document.createElement('div'); metric.className='metric-value'; metric.textContent=value.props.value ?? '—'; card.appendChild(metric); }
    else if (value.component === 'table') { const table=document.createElement('table'); const rows=value.props.rows||[]; const headers=value.props.headers||[]; const head=document.createElement('tr'); headers.forEach(x=>{const th=document.createElement('th');th.textContent=x;head.appendChild(th)}); table.appendChild(head); rows.forEach(row=>{const tr=document.createElement('tr');row.forEach(x=>{const td=document.createElement('td');td.textContent=x;tr.appendChild(td)});table.appendChild(tr)}); card.appendChild(table); }
    else { const body=document.createElement('p'); body.textContent=value.props.message || value.props.text || ''; card.appendChild(body); }
    messages.appendChild(card); messages.scrollTop = messages.scrollHeight;
  }
  async function send(event) {
    event.preventDefault(); if (button.disabled) return;
    const text = composer.value.trim(); if (!text) return;
    const body = new FormData(form);
    addMessage('user', text); composer.value=''; button.disabled=true; bubble=addMessage('assistant'); log('Run requested');
    try {
      const response = await fetch('/api/chat', {method:'POST', body});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer='';
      while(true){ const {value,done}=await reader.read(); if(done) break; buffer+=decoder.decode(value,{stream:true});
        const frames=buffer.split('\n\n'); buffer=frames.pop()||'';
        for(const frame of frames){ const line=frame.split('\n').find(x=>x.startsWith('data:')); if(!line) continue;
          const ev=JSON.parse(line.slice(5));
          if(ev.type==='TEXT_MESSAGE_CONTENT') { bubble.textContent += ev.delta || ''; messages.scrollTop=messages.scrollHeight; }
          else if(ev.type==='RUN_STARTED') log('Run started', ev.runId?.slice(0,8));
          else if(ev.type==='TOOL_CALL_START') log(`Tool · ${ev.toolCallName}`, 'Waiting for governed result');
          else if(ev.type==='TOOL_CALL_RESULT') log('Tool completed', ev.content?.slice(0,80));
          else if(ev.type==='STATE_SNAPSHOT') log(`State · ${ev.snapshot?.status || 'updated'}`);
          else if(ev.type==='CUSTOM' && ev.name==='human_interrupt') { log('Human help requested', ev.value?.message || 'Take control in Computers'); }
          else if(ev.type==='CUSTOM') renderUI(ev.value);
          else if(ev.type==='RUN_ERROR') { bubble.textContent += `\n${ev.message}`; log('Run failed',ev.message); }
          else if(ev.type==='RUN_FINISHED') log('Run finished');
        }
      }
    } catch(err) { bubble.textContent = `Unable to complete the run: ${err.message}`; log('Connection error',err.message); }
    finally { button.disabled=false; composer.focus(); }
  }
  form.addEventListener('submit', send);
  composer.addEventListener('keydown', e => { if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();form.requestSubmit();} });
  messages.scrollTop=messages.scrollHeight;
})();
