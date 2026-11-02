import { useEffect, useState } from "react";
import Login from "./Login";
import Dashboard from "./Dashboard";
import { api } from "./api";

export default function App() {
  const [session, setSession] = useState(null);
  const [checking, setChecking] = useState(true);
  useEffect(() => {
    const initData = window.Telegram?.WebApp?.initData || new URLSearchParams(window.location.hash.slice(1)).get("tgWebAppData");
    const check = initData ? api.telegramLogin(initData) : api.me();
    check.then(setSession).catch(() => {}).finally(() => setChecking(false));
    const expired = () => setSession(null);
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  const [setup,setSetup]=useState(false);
  if (checking || !session || setup) return <Login checking={checking} initialMode={setup?"register":"login"}
    onCancel={setup?()=>setSetup(false):undefined} onAuthenticated={result=>{setSession(result);setSetup(false);}} />;
  return <Dashboard session={session} onSetup={()=>setSetup(true)} onSession={setSession} onLogout={async () => {await api.logout();setSession(null);}}/>;
}
