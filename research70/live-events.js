/* Cursor/replay adapter around the browser's native EventSource. */
class PapertrailEventFeed{
 constructor(onRecord,onState){this.onRecord=onRecord;this.onState=onState;this.rows=new Map();this.cursor=0;this.job=null;this.source=null;this.terminal=null;this.resets=0;this.waiters=[];this.retryTimer=null}
 start(job){this.stop();if(this.job!==job){this.rows.clear();this.cursor=0;this.terminal=null;this.resets=0;this.job=job}const source=new EventSource('/lab/jobs/'+encodeURIComponent(job)+'/events?after='+this.cursor);this.source=source;
  source.onopen=()=>this.onState('connected');
  source.addEventListener('record',event=>{let row;try{row=JSON.parse(event.data)}catch{this.onState('error',{error:'事件格式不合法'});this.stop();return}if(!Number.isInteger(row.id)||String(row.id)!==event.lastEventId){this.onState('error',{error:'事件序号不合法'});this.stop();return}if(row.id<=this.cursor)return;if(row.id!==this.cursor+1){this.stop();this.onState('reconnecting',{error:'补齐事件序号'});if(++this.resets<=3)this.retryTimer=setTimeout(()=>{if(this.job===job)this.start(job)},1000);else this.onState('error',{error:'事件存在缺口，等待最终响应核查'});return}this.rows.set(row.id,row);this.cursor=row.id;this.onRecord(row,[...this.rows.values()])});
  source.addEventListener('job_state',event=>{const value=JSON.parse(event.data);this.terminal=value;this.stop();this.onState('finished',value);for(const resolve of this.waiters.splice(0))resolve(value)});
  source.addEventListener('stream_error',event=>{this.onState('error',JSON.parse(event.data));this.stop()});
  source.onerror=()=>{if(this.source===source)this.onState('reconnecting')};
 }
 stop(){if(this.retryTimer){clearTimeout(this.retryTimer);this.retryTimer=null}if(this.source){this.source.close();this.source=null}}
 async drained(){if(this.terminal)return this.terminal;return Promise.race([new Promise(resolve=>this.waiters.push(resolve)),new Promise(resolve=>setTimeout(()=>resolve(null),2000))])}
}
