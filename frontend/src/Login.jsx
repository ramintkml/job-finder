import { useEffect, useState } from "react";
import "./login.css";

import Icon from "./Icon";
import BrandMark from "./BrandMark";

export default function Login({ checking, password, onPasswordChange, onSubmit, pending, error }) {
  const [visible, setVisible] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  useEffect(() => {
    document.body.classList.add("login-active");
    return () => document.body.classList.remove("login-active");
  }, []);
  const checkCaps = event => setCapsLock(Boolean(event.getModifierState?.("CapsLock")));
  return (
    <main className="login-page" lang="fa" dir="rtl" data-help-open={helpOpen}>
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
