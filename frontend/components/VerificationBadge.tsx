import {ShieldCheck, Shield} from 'lucide-react';
import './VerificationBadge.css';
export default function VerificationBadge({status,compact=false}:{status:string;compact?:boolean}){
 const verified=status==='verified';
 const label=verified?'Verified':'Not verified';
 return <span className={'verification-mark '+(verified?'is-verified':'is-unverified')} tabIndex={0} aria-label={label} title={label}>
 {verified?<ShieldCheck size={19} aria-hidden="true"/>:<Shield size={19} aria-hidden="true"/>}
 {verified?<span>Verified</span>:!compact?<span>Yet to verify</span>:null}
 <span className="verification-tooltip" aria-hidden="true">{label}</span>
 </span>;
}
