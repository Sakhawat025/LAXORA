import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {title:'LAXORA | Find clarity. Find your counsel.',description:'Explore lawyers, book consultations and manage your legal journey with LAXORA.'};
export default function RootLayout({children}:{children:React.ReactNode}) {return <html lang="en"><body>{children}</body></html>;}
