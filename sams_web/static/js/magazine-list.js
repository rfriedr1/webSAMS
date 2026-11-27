// Magazine list on Lab → Analysis (magazine_list.py): the open magazine's
// entry is marked `.is-current`; scroll it into view inside the list's own
// scroll box (never the page), so moving down the list keeps your place.
(() => {
  const installers = (window.SAMSAppInstallers = window.SAMSAppInstallers || {});

  installers.installMagazineList = () => {
    const list = document.querySelector("[data-magazine-list] .magazine-list-items");
    const current = list?.querySelector(".is-current")?.closest("li");
    if (!current) return;
    const top = current.offsetTop - list.offsetTop;
    const bottom = top + current.offsetHeight;
    if (top < list.scrollTop || bottom > list.scrollTop + list.clientHeight) {
      // Leave a couple of entries above it, so the previous magazines show too.
      list.scrollTop = Math.max(0, top - current.offsetHeight * 2);
    }
  };
})();
