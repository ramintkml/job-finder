import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import Icon from "./Icon";
import BrandMark from "./BrandMark";
import "./dashboard.css";

const NAV = [{id:"overview", label:"نمای کلی", icon:"grid"}, {id:"jobs", label:"درخواست‌های من", icon:"briefcase"}, {id:"settings", label:"تنظیمات", icon:"settings"}];
const STATUS = {ready:"آماده", improving:"در حال بهبود", pending:"در انتظار", generating:"در حال ساخت", failed:"ناموفق"};
const fa = value => new Intl.NumberFormat("fa-IR").format(value);
const when = value => { const date = new Date(value); return value && !Number.isNaN(date.getTime()) ? date.toLocaleDateString("fa-IR",{month:"short",day:"numeric"}) : "—"; };
const validScore = value => typeof value === "number" && Number.isFinite(value);
const tone = value => !validScore(value) ? "neutral" : value >= 75 ? "good" : value >= 50 ? "amber" : "muted";
const recommendation = value => ({"strong apply":"گزینه بسیار مناسب",apply:"مناسب اقدام",conditional:"نیازمند بررسی",skip:"پیشنهاد نمی‌شود"}[String(value||"").toLowerCase()] || value || "ارزیابی نشده");
const profileDraft = settings => ({applicant_name:settings.applicant_name||"",applicant_role:settings.applicant_role||"",gmail_address:settings.gmail_address||"",gmail_app_password:""});

function Modal({ title, onClose, children }) {
  const dialog = useRef(null);
  useEffect(() => { const node = dialog.current; node.showModal(); return () => node.close(); }, []);
  return <dialog ref={dialog} className="dash-modal" aria-labelledby="dash-modal-title" onCancel={event => {event.preventDefault();onClose();}} onClick={event => {if(event.target === event.currentTarget) onClose();}}>
    <div className="dash-modal-head"><h2 id="dash-modal-title">{title}</h2><button type="button" className="dash-icon-button" onClick={onClose} aria-label="بستن"><Icon name="close"/></button></div>{children}
  </dialog>;
}

function Score({ value, label }) {
  return <span className={`dash-score ${tone(value)}`} aria-label={`${label}: ${validScore(value) ? fa(value) : "هنوز محاسبه نشده"}`}>{validScore(value) ? fa(value) : "—"}<small>/۱۰۰</small></span>;
}

function ApplicationRow({ app, open, onToggle, onDelete, busy }) {
  const identity = app.company || app.title || "؟";
  const color = [...identity].reduce((sum,char) => sum + char.charCodeAt(0),0) % 4;
  return <article className={`dash-application${open ? " expanded" : ""}`}>
    <div className="dash-job-grid">
      <div className="dash-job-identity"><span className={`dash-company color-${color}`} aria-hidden="true">{identity.trim().charAt(0).toUpperCase()}</span><div><button className="dash-job-title" type="button" onClick={onToggle} aria-expanded={open}><bdi>{app.title || "فرصت شغلی بدون عنوان"}</bdi></button><span className="dash-company-name"><bdi>{app.company || "نام شرکت ثبت نشده"}</bdi></span></div></div>
      <div className="dash-score-cell"><span className="dash-mobile-label">تناسب</span><Score value={app.fit_score} label="تناسب شغلی"/></div>
      <div className="dash-score-cell"><span className="dash-mobile-label">ATS</span><Score value={app.ats_score} label="ATS"/></div>
      <div className="dash-status-cell"><span className={`dash-status ${app.status === "failed" ? "failed" : app.status === "ready" ? "ready" : "waiting"}`}><i/>{STATUS[app.status] || "در حال بررسی"}</span></div>
      <time className="dash-date" dateTime={app.created_at || undefined}>{when(app.created_at)}</time>
      <button type="button" className={`dash-icon-button dash-expand${open ? " is-open" : ""}`} aria-label={`${open ? "بستن" : "نمایش"} جزئیات ${app.title || "درخواست"}`} aria-expanded={open} onClick={onToggle}><Icon name="chevron" size={17}/></button>
    </div>
    {open && <div className="dash-job-details">
      <div className="dash-detail-intro"><span className={`dash-advice ${tone(app.fit_score)}`}>{recommendation(app.recommendation)}</span><span className="dash-detail-date">ثبت‌شده در {when(app.created_at)}</span></div>
      {app.summary && <p className="dash-detail-copy" dir="auto">{app.summary}</p>}
      {app.ats_notes && <div className="dash-detail-note"><strong>نکات رزومه</strong><p dir="auto">{app.ats_notes}</p></div>}
      {Array.isArray(app.ats_keyword_missing) && app.ats_keyword_missing.length > 0 && <div className="dash-keywords"><span>موارد قابل بررسی:</span>{app.ats_keyword_missing.slice(0,8).map((word,index) => <span className="dash-keyword" key={`${word}-${index}`}><bdi>{word}</bdi></span>)}</div>}
      <div className="dash-detail-actions">
        {app.has_resume_docx ? <a className="dash-button primary" href={api.downloadApplicationResumeUrl(app.id)} download><Icon name="download" size={17}/>دانلود رزومه Word</a> : <span className="dash-text-note">فایل رزومه هنوز آماده نیست.</span>}
        {app.job_url && /^https?:\/\//i.test(app.job_url) && <a className="dash-button secondary" href={app.job_url} target="_blank" rel="noopener noreferrer"><Icon name="external" size={16}/>مشاهده آگهی</a>}
        <button className="dash-button text danger" type="button" disabled={busy} onClick={onDelete}><Icon name="trash" size={16}/>حذف درخواست</button>
      </div>
    </div>}
  </article>;
}

export default function Dashboard({ session, onLogout }) {
  const [tab,setTab] = useState("overview");
  const [applications,setApplications] = useState(null);
  const [health,setHealth] = useState(null);
  const [worker,setWorker] = useState(null);
  const [settings,setSettings] = useState({});
  const [draft,setDraft] = useState(profileDraft({}));
  const draftInitialized = useRef(false);
  const [loading,setLoading] = useState(true);
  const [listError,setListError] = useState("");
  const [busy,setBusy] = useState("");
  const [flash,setFlash] = useState(null);
  const [query,setQuery] = useState("");
  const [filter,setFilter] = useState("all");
  const [sort,setSort] = useState("newest");
  const [openId,setOpenId] = useState(null);
  const [deleteTarget,setDeleteTarget] = useState(null);
  const [guideOpen,setGuideOpen] = useState(false);
  const [lastRefresh,setLastRefresh] = useState(null);
  const main = useRef(null);
  const apps = applications || [];
  const dirty = JSON.stringify(draft) !== JSON.stringify(profileDraft(settings));

  const refresh = useCallback(async () => {
    const calls = [api.health(),api.listApplications()];
    if(session.is_admin) calls.push(api.workerStatus(),api.linkedInSettings());
    const results = await Promise.allSettled(calls);
    if(results[0].status === "fulfilled") setHealth(results[0].value);
    if(results[1].status === "fulfilled") {setApplications(Array.isArray(results[1].value) ? results[1].value : []);setListError("");}
    else setListError("دریافت درخواست‌ها انجام نشد. دوباره تلاش کنید.");
    if(session.is_admin && results[2].status === "fulfilled") setWorker(results[2].value);
    if(session.is_admin && results[3].status === "fulfilled") {
      const current = results[3].value?.settings || results[3].value || {};
      setSettings(current);
      if(!draftInitialized.current) {setDraft(profileDraft(current));draftInitialized.current=true;}
    }
    setLoading(false);
    const failure = results.find(result => result.status === "rejected");
    if(failure) throw failure.reason;
    setLastRefresh(new Date());
  },[session.is_admin]);

  useEffect(() => {
    refresh().catch(() => setFlash({type:"error",message:"بخشی از اطلاعات دریافت نشد. دوباره به‌روزرسانی کنید."}));
    const timer=setInterval(() => refresh().catch(() => {}),60000);
    return () => clearInterval(timer);
  },[refresh]);
  useEffect(() => {main.current?.scrollTo({top:0});},[tab]);

  async function run(key,action,message) {
    setBusy(key);setFlash(null);
    try { const result=await action();if(message) setFlash({type:"success",message});return {ok:true,value:result}; }
    catch(error) {setFlash({type:"error",message:error.status===429 ? "کمی بعد دوباره تلاش کنید." : "انجام این کار ممکن نشد. اتصال را بررسی کنید و دوباره تلاش کنید."});return {ok:false};}
    finally {setBusy("");}
  }
  async function save(event) {
    event.preventDefault();
    const payload={...draft};
    if(!payload.gmail_app_password) delete payload.gmail_app_password;
    const result=await run("save",() => api.updateLinkedInSettings(payload),"تنظیمات با موفقیت ذخیره شد.");
    if(result.ok) {const current=result.value?.settings || result.value;setSettings(current);setDraft(profileDraft(current));}
  }
  const stats = useMemo(() => ({total:apps.length,ready:apps.filter(a=>a.has_resume_docx).length,strong:apps.filter(a=>validScore(a.fit_score)&&a.fit_score>=75).length,processing:apps.filter(a=>["improving","generating","pending"].includes(a.status)).length}),[applications]);
  const visible = useMemo(() => apps.filter(app => {
    const text=`${app.title||""} ${app.company||""}`.toLocaleLowerCase();
    return (!query.trim() || text.includes(query.trim().toLocaleLowerCase())) &&
      (filter==="all" || filter==="strong" && validScore(app.fit_score) && app.fit_score>=75 || filter==="ready" && app.has_resume_docx || filter==="processing" && ["improving","generating","pending"].includes(app.status));
  }).sort((a,b)=>sort==="fit" ? (validScore(b.fit_score)?b.fit_score:-1)-(validScore(a.fit_score)?a.fit_score:-1) : (Date.parse(b.created_at)||0)-(Date.parse(a.created_at)||0)),[applications,query,filter,sort]);
  const recent = [...apps].sort((a,b)=>(Date.parse(b.created_at)||0)-(Date.parse(a.created_at)||0)).slice(0,5);
  const assessed=apps.filter(app=>validScore(app.fit_score));
  const groups=[{label:"تناسب بالا",value:stats.strong,tone:"good"},{label:"نیازمند بررسی",value:assessed.filter(a=>a.fit_score>=50&&a.fit_score<75).length,tone:"amber"},{label:"تناسب کمتر",value:assessed.filter(a=>a.fit_score<50).length,tone:"muted"}];
  const displayName=settings.applicant_name || "فضای کار من";
  const username=health?.telegram_bot_username;
  const botUrl=typeof username==="string" && /^[a-zA-Z0-9_]{5,32}$/.test(username) ? `https://t.me/${username}` : null;
  const sendingAction = label => botUrl ? <a className="dash-button primary" href={botUrl} target="_blank" rel="noopener noreferrer"><Icon name="plus" size={18}/>{label}</a> : <button type="button" className="dash-button primary" onClick={()=>setGuideOpen(true)}><Icon name="plus" size={18}/>{label}</button>;
  const renderList = list => listError ? <div className="dash-empty"><Icon name="alert" size={30}/><h3>اطلاعات دریافت نشد</h3><p>{listError}</p><button className="dash-button secondary" onClick={()=>run("refresh",refresh)} disabled={Boolean(busy)}>تلاش دوباره</button></div> : loading && applications===null ? <div className="dash-skeleton" aria-label="در حال دریافت درخواست‌ها" role="status"><i/><i/><i/></div> : list.length ? <div className="dash-table"><div className="dash-table-head dash-job-grid" aria-hidden="true"><span>فرصت شغلی</span><span>تناسب</span><span>ATS</span><span>وضعیت</span><span>تاریخ ثبت</span><span/></div>{list.map(app=><ApplicationRow key={app.id} app={app} open={openId===app.id} onToggle={()=>setOpenId(id=>id===app.id?null:app.id)} busy={Boolean(busy)} onDelete={()=>setDeleteTarget(app)}/>)}</div> : <div className="dash-empty"><span className="dash-empty-icon"><Icon name={apps.length ? "search" : "briefcase"} size={28}/></span><h3>{apps.length ? "درخواستی با این مشخصات پیدا نشد" : "اولین فرصت شما از اینجا شروع می‌شود"}</h3><p>{apps.length ? "عبارت جست‌وجو یا فیلترها را تغییر دهید." : "یک آگهی به ربات بفرستید؛ ارزیابی و رزومه شما اینجا نمایش داده می‌شود."}</p>{apps.length ? <button type="button" className="dash-button secondary" onClick={()=>{setQuery("");setFilter("all");}}>پاک‌کردن فیلترها</button> : sendingAction("ارسال اولین آگهی")}</div>;

  return <div className="workspace" dir="rtl" lang="fa">
    <aside className="dash-sidebar">
      <a href="/" className="dash-brand" aria-label="Career Pilot"><BrandMark/><span>Career Pilot<span className="dash-brand-dot">.</span></span></a>
      <span className="dash-nav-caption">فضای کار</span>
      <nav className="dash-nav" aria-label="بخش‌های داشبورد">{NAV.filter(item=>session.is_admin||item.id!=="settings").map(item=><button key={item.id} className={tab===item.id?"active":""} aria-current={tab===item.id?"page":undefined} onClick={()=>{setTab(item.id);setFlash(null);}}><Icon name={item.icon} size={19}/><span>{item.label}</span>{item.id==="jobs"&&applications!==null&&<small>{fa(apps.length)}</small>}</button>)}</nav>
      <div className="dash-sidebar-bottom"><div className="dash-sidebar-tip"><span className="dash-tip-icon"><Icon name="sparkle" size={20}/></span><strong>رزومه‌ای برای هر فرصت</strong><p>پروژه‌ها و تجربه‌های تازه را به رزومه پایه‌تان اضافه کنید.</p><button type="button" onClick={()=>setGuideOpen(true)}>راهنمای ربات<Icon name="arrow" size={15}/></button></div>
      <div className="dash-account"><span className="dash-avatar">{displayName.charAt(0).toUpperCase()}</span><div><strong><bdi>{displayName}</bdi></strong><span>{session.is_admin?"حساب مدیر":"حساب شخصی"}</span></div><button type="button" className="dash-icon-button" aria-label="خروج از حساب" title="خروج از حساب" disabled={Boolean(busy)} onClick={()=>run("logout",onLogout)}><Icon name="logout" size={18}/></button></div></div>
      <button type="button" className="dash-mobile-logout dash-icon-button" aria-label="خروج از حساب" disabled={Boolean(busy)} onClick={()=>run("logout",onLogout)}><Icon name="logout" size={19}/></button>
    </aside>
    <main className="dash-main" ref={main}>
      <header className="dash-topbar"><div className="dash-breadcrumb">فضای کار<Icon name="chevron" size={13}/><strong>{NAV.find(item=>item.id===tab)?.label}</strong></div><div className="dash-topbar-actions"><span className="dash-today">{new Date().toLocaleDateString("fa-IR",{weekday:"long",day:"numeric",month:"long"})}</span><button type="button" className={`dash-icon-button${busy==="refresh"?" spinning":""}`} aria-label="به‌روزرسانی اطلاعات" disabled={Boolean(busy)} onClick={()=>run("refresh",refresh,"اطلاعات به‌روز شد.")}><Icon name="refresh" size={18}/></button><span className="dash-top-avatar">{displayName.charAt(0).toUpperCase()}</span></div></header>
      <div className="dash-content">
        <div className="dash-page-heading"><div><span className="dash-eyebrow">مسیر شغلی شما، یک قدم روشن‌تر</span><h1>{tab==="overview"?"نگاهی به مسیر پیش رو":tab==="jobs"?"درخواست‌های من":"تنظیمات فضای کار"}</h1><p>{tab==="overview"?"فرصت‌ها، ارزیابی‌ها و رزومه‌هایتان را یکجا دنبال کنید.":tab==="jobs"?"همه فرصت‌هایی که بررسی کرده‌اید، همراه با نتیجه و رزومه متناسب.":"اطلاعات فردی و اتصال‌های خود را مدیریت کنید."}</p></div>{tab!=="settings"&&sendingAction("ارسال آگهی جدید")}</div>
        {flash&&<div role={flash.type==="error"?"alert":"status"} className={`dash-flash ${flash.type}`}><Icon name={flash.type==="error"?"alert":"check"} size={18}/><span>{flash.message}</span><button type="button" className="dash-icon-button" aria-label="بستن پیام" onClick={()=>setFlash(null)}><Icon name="close" size={16}/></button></div>}
        {tab==="overview"&&<>
          <section className="dash-welcome"><div><span className="dash-welcome-label"><Icon name="sparkle" size={16}/>فرصت بعدی، با آمادگی بیشتر</span><h2>تجربه شما، نقطه شروع ماست.</h2><p>آگهی را در ربات بفرستید؛ تناسبش را بررسی کنید و رزومه‌ای متناسب با همان فرصت بگیرید.</p><button type="button" onClick={()=>setTab("jobs")}>مشاهده درخواست‌ها<Icon name="arrow" size={17}/></button></div><div className="dash-welcome-art" aria-hidden="true"><div className="dash-mini-sheet"><Icon name="file" size={25}/><i/><i/><i/><span><Icon name="check" size={12}/>YOUR NEXT STEP</span></div><span className="dash-art-star"><Icon name="sparkle" size={26}/></span></div></section>
          <section className="dash-stats" aria-label="خلاصه درخواست‌ها">{[{label:"کل درخواست‌ها",value:stats.total,icon:"briefcase",note:"فرصت‌های ثبت‌شده شما",accent:true},{label:"رزومه آماده",value:stats.ready,icon:"file",note:"آماده دریافت فایل Word"},{label:"تناسب بالا",value:stats.strong,icon:"chart",note:"امتیاز تناسب ۷۵ یا بیشتر"},{label:"در حال پردازش",value:stats.processing,icon:"clock",note:"در انتظار تکمیل نتیجه"}].map(stat=><article className={`dash-stat${stat.accent?" accent":""}`} key={stat.label}><div><span>{stat.label}</span><span className="dash-stat-icon"><Icon name={stat.icon} size={19}/></span></div><strong>{applications===null?"—":fa(stat.value)}</strong><p>{stat.note}</p></article>)}</section>
          <div className="dash-overview-grid"><section className="dash-panel dash-recent"><div className="dash-panel-heading"><div><h2>آخرین درخواست‌ها</h2><p>تازه‌ترین فرصت‌های بررسی‌شده شما</p></div><button type="button" className="dash-inline-link" onClick={()=>setTab("jobs")}>مشاهده همه<Icon name="arrow" size={15}/></button></div>{renderList(recent)}</section>
            <div className="dash-insights"><section className="dash-panel"><div className="dash-panel-heading"><h2>تناسب فرصت‌ها</h2><Icon name="chart" size={18}/></div><p className="dash-insight-total"><strong>{applications===null?"—":fa(assessed.length)}</strong><span>فرصت ارزیابی‌شده</span></p><div className="dash-distribution" aria-label="توزیع امتیاز تناسب">{groups.map(group=><div key={group.label}><div><span><i className={group.tone}/>{group.label}</span><strong>{applications===null?"—":fa(group.value)}</strong></div><div className="dash-track"><span className={group.tone} style={{width:`${assessed.length?group.value/assessed.length*100:0}%`}}/></div></div>)}</div>{assessed.length===0&&<p className="dash-text-note">پس از اولین ارزیابی، این بخش کامل می‌شود.</p>}</section>
            {session.is_admin?<section className="dash-panel dash-services"><div className="dash-panel-heading"><h2>وضعیت اتصال‌ها</h2><span className="dash-live-dot"/></div>{[{label:"پردازش رزومه",icon:"sparkle",value:worker===null?"در حال بررسی":worker.worker_online?"آنلاین":"آفلاین",ready:worker?.worker_online},{label:"ربات تلگرام",icon:"telegram",value:health===null?"در حال بررسی":health.telegram_bot_ready?"متصل":"در دسترس نیست",ready:health?.telegram_bot_ready},{label:"ایمیل",icon:"mail",value:settings.gmail_connected?"تنظیم شده":"تنظیم نشده",ready:settings.gmail_connected}].map(service=><div className="dash-service" key={service.label}><span><Icon name={service.icon} size={17}/>{service.label}</span><span className={service.ready?"connected":""}><i/>{service.value}</span></div>)}<p className="dash-last-sync">{lastRefresh?`آخرین بررسی: ${lastRefresh.toLocaleTimeString("fa-IR",{hour:"2-digit",minute:"2-digit"})}`:"در حال دریافت اطلاعات"}</p></section>:<section className="dash-panel"><h2>رزومه‌تان را به‌روز نگه دارید</h2><p className="dash-text-note">پروژه یا تجربه جدید دارید؟ از بخش افزودن پروژه در ربات استفاده کنید.</p><button type="button" className="dash-inline-link" onClick={()=>setGuideOpen(true)}>راهنمای ربات<Icon name="arrow" size={16}/></button></section>}</div>
          </div>
        </>}
        {tab==="jobs"&&<section className="dash-panel dash-applications-panel"><div className="dash-filters"><div className="dash-search"><Icon name="search" size={18}/><input aria-label="جست‌وجوی درخواست‌ها" placeholder="عنوان شغل یا نام شرکت را جست‌وجو کنید…" value={query} onChange={event=>setQuery(event.target.value)} dir="auto"/>{query&&<button className="dash-icon-button" aria-label="پاک‌کردن جست‌وجو" onClick={()=>setQuery("")}><Icon name="close" size={15}/></button>}</div><label className="dash-sort"><span className="sr-only">مرتب‌سازی</span><select value={sort} onChange={event=>setSort(event.target.value)}><option value="newest">جدیدترین درخواست‌ها</option><option value="fit">بالاترین تناسب</option></select></label></div><div className="dash-filter-tabs" role="group" aria-label="فیلتر درخواست‌ها">{[{id:"all",label:"همه درخواست‌ها",count:stats.total},{id:"strong",label:"تناسب بالا",count:stats.strong},{id:"ready",label:"رزومه آماده",count:stats.ready},{id:"processing",label:"در حال پردازش",count:stats.processing}].map(item=><button key={item.id} type="button" className={filter===item.id?"active":""} aria-pressed={filter===item.id} onClick={()=>setFilter(item.id)}>{item.label}<span>{applications===null?"—":fa(item.count)}</span></button>)}</div>{renderList(visible)}{visible.length>0&&<div className="dash-list-footer">نمایش {fa(visible.length)} درخواست از {fa(apps.length)} مورد</div>}</section>}
        {tab==="settings"&&session.is_admin&&<>
          <form onSubmit={save} className="dash-settings-grid"><section className="dash-panel"><div className="dash-settings-heading"><span><Icon name="briefcase" size={20}/></span><div><h2>اطلاعات فردی</h2><p>نام و عنوانی که در مکاتبات استفاده می‌شود.</p></div></div><div className="dash-fields"><label htmlFor="profile-name">نام و نام خانوادگی<input id="profile-name" value={draft.applicant_name} autoComplete="name" onChange={e=>setDraft({...draft,applicant_name:e.target.value})} dir="auto"/></label><label htmlFor="profile-role">عنوان شغلی<input id="profile-role" value={draft.applicant_role} onChange={e=>setDraft({...draft,applicant_role:e.target.value})} dir="auto"/></label></div><p className="dash-field-note">برای ویرایش رزومه پایه، از ربات تلگرام استفاده کنید.</p></section>
          <section className="dash-panel"><div className="dash-settings-heading"><span><Icon name="mail" size={21}/></span><div><h2>ایمیل و مکاتبات</h2><p>اتصال اختیاری برای ارسال ایمیل‌های شغلی.</p></div></div><div className="dash-fields"><label htmlFor="profile-email">آدرس Gmail<input id="profile-email" type="email" autoComplete="email" value={draft.gmail_address} onChange={e=>setDraft({...draft,gmail_address:e.target.value})} dir="ltr" placeholder="you@gmail.com"/></label><label htmlFor="profile-gmail-password">رمز برنامه Gmail<input id="profile-gmail-password" type="password" autoComplete="new-password" value={draft.gmail_app_password} onChange={e=>setDraft({...draft,gmail_app_password:e.target.value})} dir="ltr" placeholder={settings.gmail_app_password_set?"برای حفظ رمز فعلی، خالی بگذارید":"رمز برنامه Gmail"}/></label></div><div className="dash-settings-actions"><button className="dash-button secondary" type="button" disabled={Boolean(busy)} onClick={()=>run("gmail-test",()=>api.testGmailConnection({gmail_address:draft.gmail_address,gmail_app_password:draft.gmail_app_password}),"اتصال Gmail تأیید شد.")}>بررسی اتصال</button><button className="dash-button text" type="button" disabled={Boolean(busy)||!settings.gmail_connected} onClick={()=>run("gmail-send",api.testGmailSend,"ایمیل آزمایشی ارسال شد.")}>ارسال ایمیل آزمایشی</button></div></section>
          <div className="dash-save-bar"><span>{dirty?"تغییرات شما هنوز ذخیره نشده‌اند.":"تغییری برای ذخیره وجود ندارد."}</span><button type="submit" className="dash-button primary" disabled={Boolean(busy)||!dirty}>{busy==="save"?<><span className="login-spinner"/>در حال ذخیره…</>:<><Icon name="check" size={17}/>ذخیره تغییرات</>}</button></div></form>
          <section className="dash-panel dash-linkedin"><div className="dash-settings-heading"><span className="dash-linkedin-icon" aria-hidden="true">in</span><div><h2>پروفایل لینکدین</h2><p>{settings.linkedin_connected?"پروفایل شما متصل است.":"برای همگام‌سازی اطلاعات پروفایل، حساب خود را متصل کنید."}</p></div></div><div className="dash-settings-actions">{!settings.linkedin_connected?<a className="dash-button secondary" href="/api/linkedin/connect"><Icon name="external" size={16}/>اتصال لینکدین</a>:<><button className="dash-button secondary" disabled={Boolean(busy)} onClick={()=>run("sync",async()=>{const result=await api.syncLinkedInProfile();const current=result.settings||result;setSettings(current);if(!dirty)setDraft(profileDraft(current));},"اطلاعات پروفایل همگام شد.")}>همگام‌سازی پروفایل</button><button className="dash-button text danger" disabled={Boolean(busy)} onClick={()=>run("disconnect",async()=>{await api.disconnectLinkedIn();await refresh();},"اتصال لینکدین قطع شد.")}>قطع اتصال</button></>}</div></section>
        </>}
        <footer className="dash-footer"><span dir="ltr">Career Pilot</span><span>فضای شخصی مدیریت درخواست‌های شغلی</span></footer>
      </div>
    </main>
    {guideOpen&&<Modal title="از ربات شروع کنید" onClose={()=>setGuideOpen(false)}><p className="dash-modal-copy">یک آگهی شغلی را در گفت‌وگوی خصوصی ربات ارسال کنید. نتیجه ارزیابی و رزومه متناسب، در همین داشبورد نمایش داده می‌شود.</p><div className="dash-guide-steps"><div><span>۱</span><p>دستور <code>/apply</code> را بفرستید و متن یا لینک آگهی را ارسال کنید.</p></div><div><span>۲</span><p>برای افزودن پروژه و تجربه تازه، از <code>/addproject</code> استفاده کنید.</p></div><div><span>۳</span><p>رزومه پایه را با دستور <code>/basecv</code> دریافت کنید.</p></div></div>{botUrl&&<a className="dash-button primary" href={botUrl} target="_blank" rel="noopener noreferrer"><Icon name="telegram" size={18}/>باز کردن ربات</a>}</Modal>}
    {deleteTarget&&<Modal title="این درخواست حذف شود؟" onClose={()=>{if(!busy)setDeleteTarget(null);}}><p className="dash-modal-copy">درخواست <bdi><strong>{deleteTarget.title||"انتخاب‌شده"}</strong></bdi> از فهرست شما حذف می‌شود.</p><div className="dash-modal-actions"><button type="button" className="dash-button secondary" disabled={Boolean(busy)} onClick={()=>setDeleteTarget(null)}>انصراف</button><button type="button" className="dash-button delete" disabled={Boolean(busy)} onClick={async()=>{const result=await run(`delete-${deleteTarget.id}`,async()=>{await api.deleteApplication(deleteTarget.id);setApplications(current=>current.filter(app=>app.id!==deleteTarget.id));if(openId===deleteTarget.id)setOpenId(null);},"درخواست حذف شد.");if(result.ok)setDeleteTarget(null);}}>{busy.startsWith("delete-")?"در حال حذف…":"حذف درخواست"}</button></div>{flash?.type==="error"&&<p className="dash-modal-error" role="alert">{flash.message}</p>}</Modal>}
  </div>;
}
