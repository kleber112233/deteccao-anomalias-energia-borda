const $=id=>document.getElementById(id), J=async(u,b)=>{const r=await fetch(u,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:undefined);const j=await r.json();if(!r.ok)throw new Error(j.detail||r.status);return j};
const fmt=(x,d=0)=>x==null?'-':Number(x).toLocaleString('pt-BR',{minimumFractionDigits:d,maximumFractionDigits:d});
const RAMPA=['#eceae4','#cde2fb','#86b6ef','#3987e5','#1c5cab','#0d366b'], FAIXAS=[1,10,100,500,2000];
const cor=w=>RAMPA[w<FAIXAS[0]?0:w<FAIXAS[1]?1:w<FAIXAS[2]?2:w<FAIXAS[3]?3:w<FAIXAS[4]?4:5];
const ABR={geladeira:'GEL',freezer:'FRZ',tv:'TV',lampada:'LUZ',chuveiro_eletrico:'CHU',ar_condicionado:'AR',ventilador:'VEN',micro_ondas:'MIC',air_fryer:'FRY',cafeteira:'CAF',maquina_lavar:'LAV',ferro_passar:'FER',roteador:'WIFI',liquidificador:'LIQ',purificador_agua:'PUR',videogame:'JOGO',notebook:'NOTE',monitor:'MON',computador_desktop:'PC',secador_cabelo:'SEC',bomba_dagua:'BOMB',bomba_piscina:'PISC',motor_portao:'PORT',carregador_veicular:'VE',lava_loucas:'LOUÇ',forno_eletrico:'FOR',secadora:'SECA',aquecedor:'AQU'};
const NOMEF={magnitude:'Consumo acima do normal',fora_de_horario:'Ligado fora de horário',duracao_excessiva:'Ligado por tempo demais',pico:'Picos rápidos',queda:'Queda de consumo',consumo_nao_explicado:'Consumo não explicado',falta_energia:'Falta de energia'};
let CAT=null,CEN=null,EST=null,alvoSel=null;
$('legenda').innerHTML=RAMPA.map((c,i)=>`<span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:${c};border:1px solid #c9c8c2;vertical-align:-1px"></span> ${i==0?'desligado':i==5?'≥ 2 kW':'< '+FAIXAS[i]+' W'}`).join(' &nbsp;');

// ---------------------------------------------------------------- abas e início
$('aPainel').onclick=()=>aba(true);$('aMont').onclick=()=>aba(false);
function aba(p){$('painel').classList.toggle('oculto',!p);$('mont').classList.toggle('oculto',p);$('aPainel').classList.toggle('ativa',p);$('aMont').classList.toggle('ativa',!p)}
async function listar(){const l=await J('/api/cenarios');for(const s of [$('cen'),$('mBase')]){const v=s.value;s.innerHTML=l.map(n=>`<option>${n}</option>`).join('');if(l.includes(v))s.value=v}}
async function carregarCen(){CEN=await J('/api/cenario/'+$('cen').value);desenharPlanta();alvos()}
$('cen').onchange=carregarCen;
$('bIni').onclick=async()=>{try{await carregarCen();const r=await J('/api/iniciar',{cenario:$('cen').value,data:$('data').value,hora:$('hora').value,velocidade:+$('vel').value,semente:+$('sem').value,mqtt_host:$('mqtt').value,bandeira:$('band').value});if($('mqtt').value&&!r.mqtt.ativo)alert('Sem conexão com o broker MQTT: '+r.mqtt.erro+'\nA simulação segue só no painel.')}catch(e){alert(e.message)}};
$('bPar').onclick=()=>J('/api/parar',{});
$('vel').onchange=()=>EST&&!EST.parado&&J('/api/velocidade',{velocidade:+$('vel').value});
$('band').onchange=()=>EST&&!EST.parado&&J('/api/bandeira',{bandeira:$('band').value});

// ---------------------------------------------------------------- falhas
function alvos(){const t=$('fTipo').value;$('fDesc').textContent=CAT.descricao_falhas[t];const l=CEN?CEN.alvos_falha[t]:[];
 $('fAlvo').innerHTML=l.map(a=>`<option value="${a}">${a=='geral'?'medidor geral (casa toda)':a=='rede'?'rede elétrica':rotulo(a)}</option>`).join('');
 if(alvoSel&&l.includes(alvoSel))$('fAlvo').value=alvoSel}
const rotulo=id=>{const i=CEN&&CEN.instancias.find(x=>x.id==id);return i?`${i.tipo.replace(/_/g,' ')} (${i.comodo})`:id};
$('fTipo').onchange=alvos;
$('bFalha').onclick=async()=>{const t=$('fTipo').value,v=$('fInt').value,p={};if(v)p[t=='consumo_nao_explicado'?'potencia_w':'fator']=+v;
 try{await J('/api/falha',{tipo:t,alvo:$('fAlvo').value,duracao_min:$('fDur').value?+$('fDur').value:null,params:p})}catch(e){alert(e.message)}};

// ---------------------------------------------------------------- planta 2D
function desenharPlanta(){if(!CEN)return;const peso={sala:1.7,cozinha:1.3,quarto:1.25,banheiro:.8,servico:.9,externa:1.6,escritorio:1};
 const W=1000,H=178,linhas=[[]];let soma=0;for(const c of CEN.comodos){const p=peso[c.tipo]||1;if(soma+p>4.6){linhas.push([]);soma=0}linhas[linhas.length-1].push([c,p]);soma+=p}
 let s=`<svg viewBox="0 0 ${W} ${linhas.length*H+4}" style="width:100%;background:#fff;border-radius:8px">`;
 linhas.forEach((ln,li)=>{const tot=ln.reduce((a,b)=>a+b[1],0);let x=2;for(const [c,p] of ln){const w=(W-4)*p/tot,y=li*H+2;
  s+=`<rect x="${x}" y="${y}" width="${w}" height="${H}" fill="#fcfcfb" stroke="#8b8a84" stroke-width="2"/><text x="${x+8}" y="${y+17}" font-size="12.5" font-weight="600" fill="#0b0b0b">${c.nome}</text><text data-com="${c.nome}" x="${x+w-8}" y="${y+17}" font-size="12" text-anchor="end" fill="#52514e"></text>`;
  const ins=CEN.instancias.filter(i=>i.comodo==c.nome),porl=Math.max(1,Math.floor((w-20)/58));
  ins.forEach((i,k)=>{const cx=x+34+(k%porl)*58,cy=y+50+Math.floor(k/porl)*62;
   s+=`<g class="ap" data-id="${i.id}" style="cursor:pointer"><circle id="c_${i.id}" cx="${cx}" cy="${cy}" r="19" fill="${RAMPA[0]}" stroke="#8b8a84" stroke-width="1.5"/><text id="t_${i.id}" x="${cx}" y="${cy+4}" font-size="10.5" font-weight="600" text-anchor="middle" fill="#0b0b0b">${ABR[i.tipo]||i.tipo.slice(0,3).toUpperCase()}${i.quantidade>1?'×'+i.quantidade:''}</text><text id="w_${i.id}" x="${cx}" y="${cy+33}" font-size="10.5" text-anchor="middle" fill="#52514e"></text>${i.canal?`<text x="${cx+17}" y="${cy-15}" font-size="9" fill="#52514e">${i.canal.split('_')[0].toUpperCase()}</text>`:''}</g>`});
  x+=w}});
 $('planta').innerHTML=s+'</svg>';
 document.querySelectorAll('.ap').forEach(g=>{g.onclick=()=>{alvoSel=g.dataset.id;const t=$('fTipo').value;if(!CEN.alvos_falha[t].includes(alvoSel)){const ok=CAT.tipos_falha.find(x=>CEN.alvos_falha[x].includes(alvoSel));if(ok)$('fTipo').value=ok}alvos()};
  g.onmousemove=e=>{const i=CEN.instancias.find(x=>x.id==g.dataset.id),w=EST&&EST.aparelhos?EST.aparelhos[i.id]:null;dica(e,`${i.nome} · ${i.tensao} V · nominal ${fmt(i.potencia_w)} W${w!=null?' · agora '+fmt(w,1)+' W':''}${i.canal?' · medidor '+i.canal.toUpperCase():' · só no medidor geral'}`)};g.onmouseleave=()=>$('dica').style.display='none'})}
function dica(e,t){const d=$('dica');d.textContent=t;d.style.display='block';d.style.left=Math.min(innerWidth-320,e.clientX+12)+'px';d.style.top=(e.clientY+14)+'px'}

// ---------------------------------------------------------------- painel ao vivo
function kpi(r,v,s){return `<div class="cartao kpi"><div class="r">${r}</div><div class="v">${v}</div><div class="s">${s||''}</div></div>`}
function atualizar(e){EST=e;if(e.parado){$('st').textContent='parado';$('st').className='tag';return}
 $('st').textContent=(e.sem_energia?'SEM ENERGIA · ':'')+'rodando · MQTT '+(e.mqtt.ativo?'conectado':'desligado')+' · '+fmt(e.mqtt.enviadas)+' msgs';$('st').className='tag '+(e.sem_energia?'crit':'ok');
 const casa=e.moradores.filter(m=>m.em_casa).map(m=>m.nome+(m.dormindo?' (dorme)':'')).join(', ')||'ninguém';
 $('kpis').innerHTML=kpi('Potência agora (medidor geral)',e.total_medido_w==null?'-':fmt(e.total_medido_w)+' W','real: '+fmt(e.total_real_w)+' W')+kpi('Energia hoje',fmt(e.kwh_hoje,2)+' kWh',e.kwh_hoje_medido!=null?'pelo medidor: '+fmt(e.kwh_hoje_medido,2)+' kWh':'')+kpi('Custo hoje','R$ '+fmt(e.custo_hoje,2),'R$ '+fmt(e.preco_kwh,3)+'/kWh · bandeira '+e.bandeira.replace('_',' '))+kpi('Projeção do mês',fmt(e.kwh_mes_projetado)+' kWh','R$ '+fmt(e.custo_mes_projetado,2))+kpi('Clima e rede',fmt(e.temperatura_c,1)+' °C','tensão '+fmt(e.tensao_pu*100,1)+'% da nominal')+kpi(e.dia_semana+', '+e.agora.slice(0,10).split('-').reverse().join('/'),e.agora.slice(11,16),(e.familia||'')+' · em casa: '+casa);
 grafico(e.curva_5min_w);
 const cs=Object.entries(e.comodos).sort((a,b)=>b[1]-a[1]),mx=Math.max(50,...cs.map(c=>c[1]));
 $('barras').innerHTML=cs.map(([n,w])=>`<div class="linhab" title="${n}: ${fmt(w,1)} W"><span>${n}</span><div><div class="barra" style="width:${100*w/mx}%"></div></div><span style="text-align:right">${fmt(w)}</span></div>`).join('')+`<div class="linhab" title="Carga de base não medida"><span><small>carga de base</small></span><div><div class="barra" style="width:${100*e.base_w/mx}%;background:#b9b8b2"></div></div><span style="text-align:right">${fmt(e.base_w)}</span></div>`;
 const ativas=new Set(e.falhas.filter(f=>f.ativa).map(f=>f.alvo));
 for(const [id,w] of Object.entries(e.aparelhos)){const c=$('c_'+id);if(!c)continue;const k=cor(w);c.setAttribute('fill',k);$('t_'+id).setAttribute('fill',RAMPA.indexOf(k)>=3?'#fff':'#0b0b0b');$('w_'+id).textContent=w>=1?fmt(w)+' W':'';c.setAttribute('stroke',ativas.has(id)?'#d03b3b':id==alvoSel?'#0b0b0b':'#8b8a84');c.setAttribute('stroke-width',ativas.has(id)?4:id==alvoSel?2.5:1.5)}
 document.querySelectorAll('[data-com]').forEach(t=>t.textContent=fmt(e.comodos[t.dataset.com]||0)+' W');
 $('tMed').innerHTML='<tr><th>Medidor</th><th>Onde</th><th>Modelo / firmware</th><th>Envio</th><th class="n">Potência (W)</th><th class="n">Energia (kWh)</th><th>Última mensagem</th><th>Relé</th></tr>'+Object.entries(e.canais).map(([ch,c])=>`<tr><td><b>${c.medidor}</b>${ch.includes('_c')?' canal '+c.numero:''}</td><td>${c.geral?'casa toda':c.aparelhos.map(rotulo).join('; ')||c.onde}</td><td>${c.modelo.slice(0,44)}<br><small>${c.firmware}</small></td><td>${c.modo=='evento'?'por variação + 60 s':'a cada '+c.intervalo_s+' s'}</td><td class="n">${fmt(c.potencia_w,1)}</td><td class="n">${c.energia_wh==null?'-':fmt(c.energia_wh/1000,3)}</td><td>${c.ts?c.ts.slice(11,19):'-'}</td><td>${c.tem_rele?`<button class="mini" onclick="J('/api/comando',{canal:'${ch}',acao:'${c.cortado?'ligar':'desligar'}'})">${c.cortado?'religar':'desligar'}</button>${c.cortado?' <span class="tag crit">cortado</span>':''}`:'<small>sem relé</small>'}</td></tr>`).join('');
 $('lFalhas').innerHTML=e.falhas.slice().reverse().map(f=>`<div style="margin:3px 0"><span class="tag ${f.ativa?'crit':''}">${f.ativa?'ativa':'encerrada'}</span> <b>${f.id}</b> ${NOMEF[f.tipo]}: ${f.alvo=='geral'?'medidor geral':f.alvo=='rede'?'rede':rotulo(f.alvo)}<br><small>${f.inicio.slice(11,16)} às ${f.fim.slice(11,16)} · ${f.origem}</small></div>`).join('')||'<small>nenhuma</small>';
 if(e.alertas.length)$('lAlertas').innerHTML=e.alertas.slice().reverse().map(a=>`<div class="msg a">${a.recebido_em.slice(11,19)} - ${a.mensagem||a.descricao||JSON.stringify(a)}</div>`).join('')}
let GR=null;
function grafico(v){const cv=$('graf'),dpr=devicePixelRatio||1,w=cv.clientWidth,h=190;cv.width=w*dpr;cv.height=h*dpr;const g=cv.getContext('2d');g.scale(dpr,dpr);g.clearRect(0,0,w,h);
 const L=38,R=8,T=8,B=22,mx=Math.max(1,...v)/1000*1.1,X=i=>L+(w-L-R)*i/288,Y=k=>T+(h-T-B)*(1-k/mx);GR={v,X,L,w,R};
 g.font='11px system-ui';g.fillStyle='#52514e';g.strokeStyle='#e3e2dd';g.lineWidth=1;
 const passo=mx>6?2:mx>3?1:mx>1.2?.5:.25;for(let k=0;k<=mx;k+=passo){g.beginPath();g.moveTo(L,Y(k));g.lineTo(w-R,Y(k));g.stroke();g.textAlign='right';g.fillText(k.toLocaleString('pt-BR'),L-5,Y(k)+4)}
 g.textAlign='center';for(let hh=0;hh<=24;hh+=3)g.fillText(hh+'h',X(hh*12),h-6);
 g.fillStyle='rgba(235,104,52,.08)';g.fillRect(X(216),T,X(252)-X(216),h-T-B);g.fillStyle='#52514e';g.textAlign='left';g.fillText('ponta 18h–21h',X(216)+3,T+11);
 if(!v.length)return;g.strokeStyle='#2a78d6';g.lineWidth=2;g.lineJoin='round';g.beginPath();v.forEach((p,i)=>i?g.lineTo(X(i+.5),Y(p/1000)):g.moveTo(X(i+.5),Y(p/1000)));g.stroke();
 const i=v.length-1;g.fillStyle='#2a78d6';g.beginPath();g.arc(X(i+.5),Y(v[i]/1000),4,0,7);g.fill()}
$('graf').onmousemove=e=>{if(!GR||!GR.v.length)return;const r=$('graf').getBoundingClientRect(),i=Math.round((e.clientX-r.left-GR.L)/(GR.w-GR.L-GR.R)*288-.5);if(i<0||i>=GR.v.length){$('dica').style.display='none';return}
 const m=i*5;dica(e,`${String(Math.floor(m/60)).padStart(2,'0')}:${String(m%60).padStart(2,'0')}: ${fmt(GR.v[i]/1000,2)} kW`)};$('graf').onmouseleave=()=>$('dica').style.display='none';
function ligarWS(){const ws=new WebSocket((location.protocol=='https:'?'wss://':'ws://')+location.host+'/ws');ws.onmessage=m=>atualizar(JSON.parse(m.data));ws.onclose=()=>setTimeout(ligarWS,1500)}

// ---------------------------------------------------------------- montagem
let M=null;
async function mCarregar(){const c=await J('/api/cenario/'+$('mBase').value);M={bruto:JSON.parse(JSON.stringify(c.bruto)),personas:JSON.parse(JSON.stringify(c.personas))};
 $('mLig').value=/monof/i.test(M.bruto.ligacao||'')?'monofásica 127 V':'bifásica 127/220 V';mDesenhar()}
$('mBase').onchange=mCarregar;$('mLig').onchange=()=>{M.bruto.ligacao=$('mLig').value;mValidar()};
const tipoDe=id=>CAT.aparelhos.find(a=>a.id==id).tipo, tiposAp=()=>[...new Set(CAT.aparelhos.map(a=>a.tipo))].sort();
function mDesenhar(){const rot=M.bruto.medidores.filter(m=>(m.mede||[])[0]!='casa toda').map(m=>m.rotulo);
 $('mComodos').innerHTML=M.bruto.comodos.map((c,ci)=>`<div class="comodo-m"><div style="display:flex;gap:8px;align-items:center;margin-bottom:4px"><input value="${c}" onchange="mRenomear(${ci},this.value)" style="font-weight:600"><button class="mini" onclick="mAddAp(${ci})">+ aparelho</button><button class="mini" onclick="mDelCom(${ci})">remover cômodo</button></div>
 <table><tr><th>Tipo</th><th>Modelo do catálogo</th><th>Qtd</th><th>Medidor</th><th></th></tr>${M.bruto.aparelhos.map((a,ai)=>a.comodo!=c?'':`<tr><td><select onchange="mTipo(${ai},this.value)">${tiposAp().map(t=>`<option ${t==tipoDe(a.aparelho_id)?'selected':''}>${t}</option>`).join('')}</select></td>
 <td><select style="max-width:330px" onchange="mSet(${ai},'aparelho_id',this.value)">${CAT.aparelhos.filter(x=>x.tipo==tipoDe(a.aparelho_id)).map(x=>`<option value="${x.id}" ${x.id==a.aparelho_id?'selected':''}>${x.nome}: ${fmt(x.potencia_w)} W${x.preco_brl?' · R$ '+fmt(x.preco_brl):''}${x.confianca=='baixa'?' · dado incerto':''}</option>`).join('')}</select></td>
 <td><input type="number" min="1" value="${a.quantidade||1}" style="width:54px" onchange="mSet(${ai},'quantidade',+this.value)"></td>
 <td><select onchange="mSet(${ai},'medido_por',this.value||null)"><option value="">só no geral</option>${rot.map(r=>`<option ${r==a.medido_por?'selected':''}>${r}</option>`).join('')}</select></td><td><button class="mini" onclick="mDelAp(${ai})">×</button></td></tr>`).join('')}</table></div>`).join('');
 $('mMed').innerHTML='<tr><th>Rótulo</th><th>Modelo do acervo</th><th>Mede</th><th></th></tr>'+M.bruto.medidores.map((m,mi)=>{const g=(m.mede||[])[0]=='casa toda';return `<tr><td><input value="${m.rotulo}" style="width:60px" onchange="mRot(${mi},this.value)"></td>
 <td><select style="max-width:430px" onchange="mMod(${mi},this.value)">${CAT.sensores.filter(s=>g?/quadro|multicircuito/.test(s.tipo):true).map(s=>`<option value="${s.id}" ${s.id==m.modelo_id?'selected':''}>${s.nome.slice(0,60)}: ${s.corrente_max_a||'?'} A · ${s.modo=='evento'?'por variação':s.intervalo_s+' s'}${s.preco_brl?' · R$ '+fmt(s.preco_brl):''}</option>`).join('')}</select></td>
 <td>${g?'<b>casa toda</b> (medidor geral)':M.bruto.aparelhos.filter(a=>a.medido_por==m.rotulo).map(a=>a.comodo+': '+tipoDe(a.aparelho_id)).join('; ')||'<small>nada ainda: escolha este rótulo num aparelho</small>'}</td><td><button class="mini" onclick="mDelMed(${mi})">×</button></td></tr>`}).join('');
 $('mPes').innerHTML='<tr><th>Nome</th><th>Ocupação</th><th>Quarto</th><th>Acorda</th><th>Sai</th><th>Volta</th><th>Dorme</th><th>Home office</th><th>Banho (min)</th></tr>'+M.personas.moradores.map((p,pi)=>`<tr><td><input value="${p.nome}" style="width:95px" onchange="mP(${pi},'nome',this.value)"></td><td><input value="${p.ocupacao||''}" style="width:170px" onchange="mP(${pi},'ocupacao',this.value)"></td>
 <td><select onchange="mP(${pi},'quarto',this.value)">${M.bruto.comodos.map(c=>`<option ${c==p.quarto?'selected':''}>${c}</option>`).join('')}</select></td>${['acorda','sai','volta','dorme'].map(k=>`<td><input type="time" value="${p.util[k]||''}" onchange="mPu(${pi},'${k}',this.value)"></td>`).join('')}
 <td><input value="${(p.home_office||[]).join(',')}" style="width:70px" title="dias: 0 = segunda ... 4 = sexta" onchange="mP(${pi},'home_office',this.value.split(',').filter(x=>x!=='').map(Number))"></td><td><input type="number" value="${(p.banho||{}).duracao_min||9}" style="width:56px" onchange="mPb(${pi},+this.value)"></td></tr>`).join('');
 $('mJson').value=JSON.stringify(M.personas,null,1);mValidar()}
const mSet=(ai,k,v)=>{M.bruto.aparelhos[ai][k]=v;mDesenhar()},mTipo=(ai,t)=>mSet(ai,'aparelho_id',CAT.aparelhos.find(a=>a.tipo==t).id);
const mDelAp=ai=>{M.bruto.aparelhos.splice(ai,1);mDesenhar()},mAddAp=ci=>{M.bruto.aparelhos.push({comodo:M.bruto.comodos[ci],aparelho_id:CAT.aparelhos.find(a=>a.tipo=='lampada').id,quantidade:1,medido_por:null});mDesenhar()};
const mRenomear=(ci,n)=>{const o=M.bruto.comodos[ci];M.bruto.comodos[ci]=n;M.bruto.aparelhos.forEach(a=>{if(a.comodo==o)a.comodo=n});M.personas.moradores.forEach(p=>{if(p.quarto==o)p.quarto=n;if(p.chuveiro==o)p.chuveiro=n});mDesenhar()};
const mDelCom=ci=>{const o=M.bruto.comodos.splice(ci,1)[0];M.bruto.aparelhos=M.bruto.aparelhos.filter(a=>a.comodo!=o);mDesenhar()};
$('mAddCom').onclick=()=>{M.bruto.comodos.push('Novo cômodo '+(M.bruto.comodos.length+1));mDesenhar()};
const mRot=(mi,v)=>{const o=M.bruto.medidores[mi].rotulo;M.bruto.medidores[mi].rotulo=v;M.bruto.aparelhos.forEach(a=>{if(a.medido_por==o)a.medido_por=v});mDesenhar()};
const mMod=(mi,id)=>{const s=CAT.sensores.find(x=>x.id==id);Object.assign(M.bruto.medidores[mi],{modelo_id:id,modelo:s.nome,preco_brl:s.preco_brl||0});mDesenhar()};
const mDelMed=mi=>{const o=M.bruto.medidores.splice(mi,1)[0].rotulo;M.bruto.aparelhos.forEach(a=>{if(a.medido_por==o)a.medido_por=null});mDesenhar()};
$('mAddMed').onclick=()=>{const s=CAT.sensores.find(x=>x.id=='tplink-tapo-p110')||CAT.sensores[0];let n=1;while(M.bruto.medidores.some(m=>m.rotulo=='T'+n))n++;M.bruto.medidores.push({rotulo:'T'+n,modelo_id:s.id,modelo:s.nome,onde:'',preco_brl:s.preco_brl||0,mede:[]});mDesenhar()};
const mP=(pi,k,v)=>{M.personas.moradores[pi][k]=v;mDesenhar()},mPu=(pi,k,v)=>{M.personas.moradores[pi].util[k]=v||null;mDesenhar()},mPb=(pi,v)=>{(M.personas.moradores[pi].banho=M.personas.moradores[pi].banho||{}).duracao_min=v;mDesenhar()};
$('mJsonOk').onclick=()=>{try{M.personas=JSON.parse($('mJson').value);mDesenhar()}catch(e){alert('JSON inválido: '+e.message)}};
let mT=null;function mValidar(){clearTimeout(mT);mT=setTimeout(async()=>{try{const v=await J('/api/validar',{nome:$('mNome').value,cenario:M.bruto,personas:M.personas});
 $('mVal').innerHTML=`<div style="margin-bottom:8px"><span class="tag ${v.ok?'ok':'crit'}">${v.ok?'montagem compatível':v.erros.length+' erro(s)'}</span></div><table><tr><td>Aparelhos</td><td class="n">${v.n_aparelhos}</td></tr><tr><td>Canais de medição</td><td class="n">${v.n_canais}</td></tr><tr><td>Aparelhos com medidor próprio</td><td class="n">${v.medidos}</td></tr><tr><td>Custo dos medidores</td><td class="n">R$ ${fmt(v.custo_medidores,2)}</td></tr><tr><td>Custo dos aparelhos</td><td class="n">R$ ${fmt(v.custo_aparelhos,2)}</td></tr></table>`+v.erros.map(x=>`<div class="msg e">${x}</div>`).join('')+v.avisos.map(x=>`<div class="msg a">${x}</div>`).join('')+`<details><summary>${v.infos.length} aparelho(s) só no medidor geral</summary>${v.infos.map(x=>`<div class="msg i">${x}</div>`).join('')}</details>`}catch(e){$('mVal').innerHTML=`<div class="msg e">${e.message}</div>`}},250)}
$('mSalvar').onclick=async()=>{try{const r=await J('/api/salvar',{nome:$('mNome').value,cenario:M.bruto,personas:M.personas});$('mSt').innerHTML=`<span class="tag ok">salvo como ${r.nome}</span>`;await listar();$('cen').value=r.nome;await carregarCen()}catch(e){$('mSt').innerHTML=`<span class="tag crit">${e.message}</span>`}};

(async()=>{CAT=await J('/api/catalogo');$('fTipo').innerHTML=CAT.tipos_falha.map(t=>`<option value="${t}">${NOMEF[t]}</option>`).join('');await listar();$('cen').value='casa_perfil1';await carregarCen();await mCarregar();ligarWS()})();
