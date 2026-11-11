(function(){
  // topic filter chips on the News page: one pressed chip at a time
  var group=document.querySelector('[data-news-topics]');
  if(group){group.addEventListener('click',function(ev){var b=ev.target.closest('button[data-topic]');if(!b)return;var v=b.getAttribute('data-topic');
    group.querySelectorAll('button[data-topic]').forEach(function(x){x.setAttribute('aria-pressed',String(x===b));});
    document.querySelectorAll('.news-rows li[data-news-topic]').forEach(function(li){li.hidden=v!=='all'&&li.getAttribute('data-news-topic')!==v;});});}
  var box=document.getElementById('news-search');
  if(!box)return;
  // Pagefind's files are written by the indexing step after the site build; load them only when present.
  var root=box.getAttribute('data-pagefind-root');
  var css=document.createElement('link');css.rel='stylesheet';css.href=root+'pagefind-ui.css';document.head.appendChild(css);
  var js=document.createElement('script');js.src=root+'pagefind-ui.js';
  js.onload=function(){try{new PagefindUI({element:'#news-search',showSubResults:true,showImages:false,translations:{placeholder:box.getAttribute('data-placeholder')}});}catch(e){}};
  js.onerror=function(){box.hidden=true;};
  document.head.appendChild(js);
})();
