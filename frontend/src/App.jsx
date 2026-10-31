import { useEffect, useState } from "react";
import Login from "./Login";
import Dashboard from "./Dashboard";
import { api } from "./api";

export default function App() {
  const [session, setSession] = useState(null);
  const [checking, setChecking] = useState(true);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  useEffect(() => {
    const initData = window.Telegram?.WebApp?.initData || new URLSearchParams(window.location.hash.slice(1)).get("tgWebAppData");
    const check = initData ? api.telegramLogin(initData) : api.me();
    check.then(setSession).catch(() => {}).finally(() => setChecking(false));
    const expired = () => setSession(null);
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  async function login(event) {
    event.preventDefault();
    setPending(true); setError("");
    try { setSession(await api.login(password)); setPassword(""); }
    catch (err) {
      setError(err.status === 401 ? "رمز ورود درست نیست. دوباره امتحان کنید." :
        err.status === 429 ? "تعداد تلاش‌ها زیاد شده؛ چند دقیقه دیگر دوباره امتحان کنید." :
        "ارتباط با سرویس برقرار نشد. کمی بعد دوباره تلاش کنید.");
    }
    finally { setPending(false); }
  }
  if (checking || !session) return <Login checking={checking} password={password}
    onPasswordChange={value => { setPassword(value); setError(""); }}
    onSubmit={login} pending={pending} error={error} />;
  return <Dashboard session={session} onLogout={async () => {await api.logout();setSession(null);setError("");}}/>;
}
