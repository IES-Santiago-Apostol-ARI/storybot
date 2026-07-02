/* StoryBot landing — interactions */
(function () {
  'use strict';

  // --- Mobile nav toggle ---
  var toggle = document.querySelector('.nav-toggle');
  var links = document.querySelector('.nav-links');
  if (toggle && links) {
    toggle.addEventListener('click', function () {
      links.classList.toggle('open');
    });
    links.addEventListener('click', function (e) {
      if (e.target.tagName === 'A') links.classList.remove('open');
    });
  }

  // --- Scroll reveal ---
  var revealEls = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
      });
    }, { threshold: 0.12 });
    revealEls.forEach(function (el) { io.observe(el); });
  } else {
    revealEls.forEach(function (el) { el.classList.add('in'); });
  }

  // --- One audio at a time ---
  var audios = document.querySelectorAll('audio');
  audios.forEach(function (a) {
    a.addEventListener('play', function () {
      audios.forEach(function (o) { if (o !== a) o.pause(); });
    });
  });

  // --- Lightbox gallery ---
  var figures = Array.prototype.slice.call(document.querySelectorAll('.gallery figure'));
  var lb = document.getElementById('lightbox');
  if (lb && figures.length) {
    var lbImg = lb.querySelector('img');
    var current = 0;

    function open(i) {
      current = i;
      var img = figures[i].querySelector('img');
      lbImg.src = img.getAttribute('data-full') || img.src;
      lbImg.alt = img.alt;
      lb.classList.add('open');
      document.body.style.overflow = 'hidden';
    }
    function close() {
      lb.classList.remove('open');
      document.body.style.overflow = '';
    }
    function step(d) {
      open((current + d + figures.length) % figures.length);
    }

    figures.forEach(function (f, i) { f.addEventListener('click', function () { open(i); }); });
    lb.querySelector('.lb-close').addEventListener('click', close);
    lb.querySelector('.lb-prev').addEventListener('click', function (e) { e.stopPropagation(); step(-1); });
    lb.querySelector('.lb-next').addEventListener('click', function (e) { e.stopPropagation(); step(1); });
    lb.addEventListener('click', function (e) { if (e.target === lb) close(); });
    document.addEventListener('keydown', function (e) {
      if (!lb.classList.contains('open')) return;
      if (e.key === 'Escape') close();
      if (e.key === 'ArrowRight') step(1);
      if (e.key === 'ArrowLeft') step(-1);
    });
  }

  // --- Active nav link on scroll ---
  var sections = document.querySelectorAll('section[id]');
  var navAnchors = document.querySelectorAll('.nav-links a');
  window.addEventListener('scroll', function () {
    var y = window.scrollY + 90;
    sections.forEach(function (s) {
      var link = document.querySelector('.nav-links a[href="#' + s.id + '"]');
      if (!link) return;
      if (y >= s.offsetTop && y < s.offsetTop + s.offsetHeight) {
        navAnchors.forEach(function (a) { a.style.background = ''; a.style.color = ''; });
        link.style.background = 'var(--blue-soft)';
        link.style.color = 'var(--blue-deep)';
      }
    });
  }, { passive: true });
})();
