(function(){
  var sel=document.getElementById('teamfilter');
  function apply(v){
    document.querySelectorAll('.stand tr[data-team]').forEach(function(r){r.classList.toggle('hl',!!v&&r.dataset.team===v);});
    document.querySelectorAll('.rounds .round').forEach(function(rd){
      var any=false;
      rd.querySelectorAll('.match').forEach(function(m){
        var hit=!v||(' '+m.dataset.teams+' ').indexOf(' '+v+' ')>-1;
        m.hidden=!hit; if(hit) any=true;
      });
      rd.querySelectorAll('.bye').forEach(function(b){b.hidden=!!v;});
      rd.hidden=!!v&&!any;
    });
  }
  if(sel){
    var saved=''; try{saved=localStorage.getItem('vac-team')||'';}catch(e){}
    if(saved&&sel.querySelector('option[value="'+saved+'"]')){sel.value=saved;apply(saved);}
    sel.addEventListener('change',function(){apply(sel.value);try{localStorage.setItem('vac-team',sel.value);}catch(e){}});
  }
  document.querySelectorAll('[data-copy]').forEach(function(b){
    b.addEventListener('click',function(){
      var t=b.getAttribute('data-copy'),label=b.textContent;
      function done(){b.textContent=(document.documentElement.lang==='nl'?'Gekopieerd':'Copied');setTimeout(function(){b.textContent=label;},1800);}
      if(navigator.clipboard){navigator.clipboard.writeText(t).then(done,function(){});}
    });
  });
})();
