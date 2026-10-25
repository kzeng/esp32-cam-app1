"use strict";
const localTime = new Intl.DateTimeFormat("zh-CN", {dateStyle: "medium", timeStyle: "medium"});
document.querySelectorAll("time.local-time").forEach((node) => {
  const date = new Date(node.dateTime);
  if (!Number.isNaN(date.valueOf())) node.textContent = localTime.format(date);
});
document.querySelectorAll("form.delete-event").forEach((form) => form.addEventListener("submit", (event) => {
  if (!window.confirm("删除这个事件及其三张照片？此操作不能撤销。")) event.preventDefault();
}));
