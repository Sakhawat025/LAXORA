import {notFound} from 'next/navigation';
import AuthPage from '../../../components/AuthPage';
import Home from '../../../components/Workspace';
import type {Role} from '../../../lib/api';
export function generateStaticParams(){return ['client','lawyer','admin'].flatMap(role=>['login','register','dashboard'].map(action=>({role,action})));}
export const dynamicParams=false;
export default async function RolePage({params}:{params:Promise<{role:string;action:string}>}){
 const {role,action}=await params;
 if(!['client','lawyer','admin'].includes(role)||!['login','register','dashboard'].includes(action))notFound();
 if(action==='dashboard')return <Home workspaceRole={role as Role}/>;
 return <AuthPage role={role as Role} mode={action as 'login'|'register'}/>;
}
