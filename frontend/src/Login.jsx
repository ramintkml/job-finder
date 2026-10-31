import { useState } from "react";
import "./login.css";

function Icon({ name, size = 20, ...props }) {
  const paths = {
    arrow: <><path d="m14 6-6 6 6 6"/><path d="M8 12h12"/></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="3"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/><path d="M12 14v3"/></>,
    eye: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></>,
    eyeOff: <><path d="m3 3 18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.2A12 12 0 0 1 12 5c6.5 0 10 7 10 7a18 18 0 0 1-3.2 4M6.2 6.2A20 20 0 0 0 2 12s3.5 7 10 7a12 12 0 0 0 5.8-1.6"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></>,
    sparkle: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/><path d="m20 2 .6 1.4L22 4l-1.4.6L20 6l-.6-1.4L18 4l1.4-.6Z"/></>,
    alert: <><circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16h.01"/></>,
    help: <><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 17h.01"/></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}

function BrandMark() {
  return <span className="login-brand-mark" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none"><path d="m7 24 8-17 3 10 7 3-18 4Z" fill="currentColor"/><path d="m15 7 3 10-11 7" stroke="#d8e9be" strokeWidth="1.2" strokeLinejoin="round"/></svg></span>;
}

export default function Login({ checking, password, onPasswordChange, onSubmit, pending, error }) {
  const [visible, setVisible] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const checkCaps = event => setCapsLock(Boolean(event.getModifierState?.("CapsLock")));
  return (
    <main className="login-page" lang="fa" dir="rtl">
      <header className="login-header">
        <a className="login-brand" href="/" aria-label="Career Pilot، صفحه اصلی"><BrandMark /><span>Career Pilot<span className="login-brand-dot">.</span></span></a>
        <span className="login-header-note">قدم بعدی، با اطمینان بیشتر</span>
      </header>

      <div className="login-layout">
        <section className="login-story" dir="rtl" aria-labelledby="login-story-title">
          <div className="login-story-grain" aria-hidden="true" />
          <span className="login-eyebrow"><span /> همراه مسیر شغلی شما</span>
          <h2 id="login-story-title">توانایی‌های شما،<br /><span>فرصت‌های پیش رو.</span></h2>
          <p className="login-story-description">از شناخت تناسب یک فرصت شغلی تا ساخت رزومه‌ای که تجربه شما را بهتر نشان می‌دهد؛ همه در یک فضای شخصی.</p>

          <div className="login-art" aria-hidden="true" dir="ltr">
            <div className="login-art-orbit orbit-one" /><div className="login-art-orbit orbit-two" />
            <div className="login-paper-back" />
            <div className="login-resume-paper">
              <div className="login-paper-top"><span>YOUR NEXT CHAPTER</span><Icon name="sparkle" size={18} /></div>
              <div className="login-paper-title">A story worth<br />telling well.</div>
              <div className="login-paper-subtitle">EXPERIENCE. SKILLS. POSSIBILITY.</div>
              <div className="login-paper-rule" />
              <div className="login-paper-section">PROFILE</div>
              <div className="login-paper-line long" /><div className="login-paper-line" /><div className="login-paper-line short" />
              <div className="login-paper-section">SELECTED EXPERIENCE</div>
              <div className="login-paper-line long" /><div className="login-paper-line" /><div className="login-paper-tags"><span>YOUR SKILLS</span><span>YOUR EXPERIENCE</span></div>
              <div className="login-paper-bottom"><span>CURATED FOR YOUR NEXT STEP</span><span>01</span></div>
            </div>
            <div className="login-float login-float-match" dir="rtl"><span className="login-float-icon"><Icon name="check" size={18}/></span><div><strong>تجربه واقعی شما</strong><span>نقطه شروع یک رزومه بهتر</span></div></div>
            <div className="login-float login-float-resume" dir="rtl"><span className="login-float-icon"><Icon name="file" size={19}/></span><div><strong>رزومه متناسب با فرصت</strong><span>با جزئیاتی که اهمیت دارند</span></div></div>
          </div>
          <div className="login-story-footer"><span>یک مسیر روشن‌تر، از همین‌جا.</span><span className="login-story-lines" aria-hidden="true"><i/><i/><i/></span></div>
        </section>

        <section className="login-form-panel" dir="rtl" aria-labelledby="login-title" aria-busy={checking || pending}>
          <div className="login-form-content">
            <div className="login-welcome-icon"><Icon name="lock" size={24}/></div>
            <span className="login-section-label">فضای کار شخصی شما</span>
            <h1 id="login-title">خوش برگشتید.</h1>
            <p className="login-form-intro">برای ادامه مسیر، وارد داشبورد خود شوید.</p>
            {checking ? <div className="login-checking" role="status"><span className="login-spinner"/>در حال بررسی دسترسی شما…</div> : <form className="login-form" onSubmit={onSubmit}>
              <label htmlFor="dashboard-password">رمز ورود داشبورد</label>
              <div className={`login-input-wrap${error ? " has-error" : ""}`}>
                <Icon name="lock" size={19}/>
                <input id="dashboard-password" name="password" type={visible ? "text" : "password"} autoComplete="current-password" required value={password} onChange={event => onPasswordChange(event.target.value)} onKeyDown={checkCaps} onKeyUp={checkCaps} onBlur={() => setCapsLock(false)} placeholder="رمز خود را وارد کنید" disabled={pending} dir="ltr" aria-invalid={Boolean(error)} aria-describedby={error ? "login-error" : capsLock ? "login-caps" : undefined}/>
                <button className="login-eye" type="button" onClick={() => setVisible(value => !value)} aria-label={visible ? "پنهان کردن رمز" : "نمایش رمز"} aria-pressed={visible} disabled={pending}><Icon name={visible ? "eyeOff" : "eye"} size={20}/></button>
              </div>
              {capsLock && <p id="login-caps" className="login-caps" role="status">کلید Caps Lock روشن است.</p>}
              {error && <div id="login-error" className="login-error" role="alert"><Icon name="alert" size={18}/><span>{error}</span></div>}
              <button className="login-submit" type="submit" disabled={pending || !password.trim()}>{pending ? <><span className="login-spinner"/>در حال ورود…</> : <>ورود به داشبورد<Icon name="arrow" size={20}/></>}</button>
              <button className="login-help-toggle" type="button" onClick={() => setHelpOpen(value => !value)} aria-expanded={helpOpen} aria-controls="login-help"><Icon name="help" size={16}/>برای ورود به راهنمایی نیاز دارید؟</button>
              {helpOpen && <p id="login-help" className="login-help">از رمز ورود اختصاصی داشبورد استفاده کنید. اگر به آن دسترسی ندارید، با مدیر سرویس تماس بگیرید.</p>}
            </form>}
            <div className="login-divider"><span>همراه شما در هر قدم</span></div>
            <div className="login-features"><span><Icon name="file" size={17}/>رزومه شخصی</span><span><Icon name="sparkle" size={17}/>بررسی تناسب شغلی</span></div>
            <p className="login-telegram-note">برای ارسال آگهی و به‌روزرسانی رزومه، از ربات تلگرام استفاده کنید.</p>
          </div>
          <div className="login-form-footnote"><span className="login-privacy-dot"/>اطلاعات هر کاربر، در فضای اختصاصی خودش</div>
        </section>
      </div>
      <footer className="login-footer"><span dir="ltr">© {new Date().getFullYear()} Career Pilot</span><span>برای قدم‌هایی که ارزش برداشتن دارند.</span></footer>
    </main>
  );
}
