const num = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 3 });
const time = new Intl.DateTimeFormat("en-US", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "America/Sao_Paulo",
});

export const formatNumber = (n: number | undefined) => (n === undefined ? "—" : num.format(n));
export const formatTime = (iso: string) => time.format(new Date(iso));
