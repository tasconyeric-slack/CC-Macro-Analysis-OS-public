(function(){
  var sel=document.querySelector('select[data-news-topic]');
  if(sel){sel.addEventListener('change',function(){var v=sel.value;document.querySelectorAll('.news-rows li[data-news-topic]').forEach(function(li){li.hidden=v!=='all'&&li.getAttribute('data-news-topic')!==v;});});}
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
