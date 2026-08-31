// Minimal DOM stub good enough to run static/children/script.js
class ClassList {
  constructor(el){ this.el = el; this.s = new Set(); }
  add(...c){ c.forEach(x=>this.s.add(x)); }
  remove(...c){ c.forEach(x=>this.s.delete(x)); }
  contains(c){ return this.s.has(c); }
  toggle(c){ this.s.has(c) ? this.s.delete(c) : this.s.add(c); }
}
class El {
  constructor(tag='div', attrs={}){
    this.tagName = tag.toUpperCase();
    this.classList = new ClassList(this);
    this.children = [];
    this.style = { setProperty(){}, removeProperty(){}, getPropertyValue(){return '';} };
    this.dataset = {};
    this._html = '';
    this.textContent = '';
    this.attrs = attrs;
    this.hidden = false;
  }
  get innerHTML(){ return this._html; }
  set innerHTML(v){ this._html = v; if (v === '') this.children = []; }
  appendChild(c){ this.children.push(c); return c; }
  removeChild(c){ this.children = this.children.filter(x=>x!==c); }
  querySelector(sel){ return getEl('child:'+(this.attrs.id||this.tagName)+':'+sel); }
  querySelectorAll(sel){ return [getEl('child:'+(this.attrs.id||this.tagName)+':'+sel)]; }
  addEventListener(){}
  removeEventListener(){}
  getAttribute(k){ return this.attrs[k] ?? null; }
  setAttribute(k,v){ this.attrs[k]=v; }
  closest(){ return null; }
  focus(){}
  play(){ return Promise.resolve(); }
  pause(){}
  load(){}
}
const registry = new Map();
function getEl(id){
  if(!registry.has(id)) registry.set(id, new El('div',{id}));
  return registry.get(id);
}
const document = {
  _els: registry,
  getElementById: (id)=>getEl(id),
  createElement: (tag)=>new El(tag),
  querySelector: (sel)=>getEl('sel:'+sel),
  querySelectorAll: (sel)=>[getEl('sel:'+sel)],
  addEventListener: ()=>{},
  body: new El('body'),
  documentElement: new El('html'),
};
module.exports = { document, El, getEl, registry };
