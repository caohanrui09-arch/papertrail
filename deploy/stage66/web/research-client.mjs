export async function requestJSON(path,body,signal){
 const r=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,signal});
 const value=await r.json();if(!r.ok){const error=Error(typeof value.detail==='string'?value.detail:'请求失败（'+r.status+'）');error.status=r.status;throw error;}return value;
}
