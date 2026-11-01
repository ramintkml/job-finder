import grid from "./assets/coolicons/grid.svg?raw";
import briefcase from "./assets/coolicons/briefcase.svg?raw";
import settings from "./assets/coolicons/settings.svg?raw";
import logout from "./assets/coolicons/logout.svg?raw";
import refresh from "./assets/coolicons/refresh.svg?raw";
import search from "./assets/coolicons/search.svg?raw";
import download from "./assets/coolicons/download.svg?raw";
import external from "./assets/coolicons/external.svg?raw";
import mail from "./assets/coolicons/mail.svg?raw";
import clock from "./assets/coolicons/clock.svg?raw";
import plus from "./assets/coolicons/plus.svg?raw";
import close from "./assets/coolicons/close.svg?raw";
import chevron from "./assets/coolicons/chevron.svg?raw";
import telegram from "./assets/coolicons/telegram.svg?raw";
import chart from "./assets/coolicons/chart.svg?raw";
import trash from "./assets/coolicons/trash.svg?raw";
import arrow from "./assets/coolicons/arrow.svg?raw";
import lock from "./assets/coolicons/lock.svg?raw";
import eye from "./assets/coolicons/eye.svg?raw";
import eyeOff from "./assets/coolicons/eyeOff.svg?raw";
import check from "./assets/coolicons/check.svg?raw";
import file from "./assets/coolicons/file.svg?raw";
import sparkle from "./assets/coolicons/sparkle.svg?raw";
import alert from "./assets/coolicons/alert.svg?raw";
import help from "./assets/coolicons/help.svg?raw";

const icons = {grid,briefcase,settings,logout,refresh,search,download,external,mail,clock,plus,close,chevron,telegram,chart,trash,arrow,lock,eye,eyeOff,check,file,sparkle,alert,help};

// SVG artwork from the supplied Coolicons v4.1 pack; color follows the control.
export default function Icon({ name, size = 20, ...props }) {
  const markup = icons[name];
  if (!markup) throw new Error(`Unknown icon: ${name}`);
  return <svg className="ui-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" {...props} dangerouslySetInnerHTML={{__html:markup.replace(/^<svg[^>]*>/, "").replace(/<\/svg>\s*$/, "")}} />;
}
