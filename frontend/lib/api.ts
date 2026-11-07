let sessionRole:string|undefined;
let sessionUser:number|undefined;
export function setSessionContext(role?:string,id?:number){sessionRole=role;sessionUser=id;}
export async function api<T=unknown>(path:string,method='GET',body?:unknown):Promise<T>{
 const isForm=body instanceof FormData;
 const response=await fetch('/api'+path,{method,credentials:'same-origin',headers:{'X-Laxora-Request':'1',...(sessionRole?{'X-Laxora-Role':sessionRole}:{}),...(sessionUser?{'X-Laxora-User':String(sessionUser)}:{}),...(!isForm&&body?{'Content-Type':'application/json'}:{})},body:body?(isForm?body:JSON.stringify(body)):undefined,cache:'no-store'});
 const data=await response.json().catch(()=>({detail:'Unable to connect. Please try again.'}));
 if(!response.ok)throw new Error(Array.isArray(data.detail)?data.detail.map((e:{msg:string})=>e.msg).join('. '):data.detail||'Request failed');
 return data;
}
export type Role='client'|'lawyer'|'admin';
export type Account={photo_url?:string;id:number;name:string;email:string;role:Role;phone:string;city:string;address:string;bio:string;active:boolean;created_at:string};
export type Thread={id:number;client_id:number;lawyer_user_id:number;client_name:string;lawyer_name:string;other_id:number;other_name:string;other_role:string;can_message:boolean;last_message:string;updated_at:string;unread:number};
export const initials=(s:string)=>s.split(' ').slice(0,2).map(x=>x[0]).join('');
export const date=(s:string)=>new Date(s).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
