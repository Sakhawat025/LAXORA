'use client';
import {useState} from 'react';
import {Camera,Upload,Trash2} from 'lucide-react';
import {api,initials} from '../lib/api';
export default function ProfilePhoto({user,onUpdated}:{user:{name:string;photo_url?:string};onUpdated:()=>Promise<void>}){
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 return <section className="panel photo-panel"><div className="photo-preview">{user.photo_url?<img src={user.photo_url} alt={user.name}/>:<span>{initials(user.name)}</span>}<Camera size={19}/></div><div><h2>Your profile picture</h2><p>JPG, PNG or WebP · up to 5 MB. Lawyers’ photos appear on their public profile.</p><div className="actions"><label className="btn gold photo-upload"><Upload size={16}/>{busy?'Uploading…':'Choose a photo'}<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={async e=>{const f=e.target.files?.[0];if(!f)return;setError('');if(f.size>5*1024*1024){setError('Choose a photo smaller than 5 MB');return;}setBusy(true);try{const data=new FormData();data.set('file',f);await api('/auth/photo','POST',data);await onUpdated();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}/></label>{user.photo_url&&<button disabled={busy} className="btn outline" onClick={async()=>{setBusy(true);try{await api('/auth/photo','DELETE');await onUpdated();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}><Trash2 size={15}/>Remove</button>}</div>{error&&<p className="error" role="alert">{error}</p>}</div></section>;
}
