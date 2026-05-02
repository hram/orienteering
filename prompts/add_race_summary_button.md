# Задача: добавить кнопку анализа достижимости на экран протокола

## Контекст

На экране протокола есть блок `race-summary` — сводная информация о забеге (участники, КП, выбранный спортсмен).

Нужно добавить кнопку **"Анализ достижимости"**, по нажатию на которую открывается модальный диалог с интерактивным графиком.

Готовый HTML-виджет графика уже лежит в файле:
```
prompts/jenks_zones.html
```

---

## Что нужно сделать

### 1. Добавить кнопку в блок `race-summary`

Найди блок `race-summary` на странице протокола и добавь кнопку рядом с остальными элементами блока:

```html
<button class="button compact" type="button" id="open-zones-btn">
  Анализ достижимости
</button>
```

Стиль — как у существующих кнопок в проекте (класс `button compact`).

---

### 2. Создать модальный диалог

Добавь в конец `<body>` страницы следующую разметку:

```html
<div id="zones-modal" class="modal-overlay" hidden>
  <div class="modal-dialog">
    <div class="modal-header">
      <h2>Анализ достижимости</h2>
      <button class="icon-button" type="button" id="close-zones-btn" aria-label="Закрыть">×</button>
    </div>
    <div class="modal-body" id="zones-modal-body">
      <!-- виджет загружается сюда -->
    </div>
  </div>
</div>
```

---

### 3. Добавить стили модального окна

Добавь в `static/style.css`:

```css
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgb(0 0 0 / 45%);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
}

.modal-overlay[hidden] {
  display: none;
}

.modal-dialog {
  background: #ffffff;
  border-radius: 12px;
  width: 100%;
  max-width: 780px;
  max-height: 90vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #e3e9ed;
  position: sticky;
  top: 0;
  background: #ffffff;
  z-index: 1;
}

.modal-header h2 {
  margin: 0;
  font-size: 18px;
}

.modal-body {
  padding: 20px;
  overflow-y: auto;
}
```

---

### 4. Добавить JavaScript

Добавь в конец страницы (или в отдельный `static/zones-modal.js`):

```javascript
(function () {
  const btn = document.querySelector('#open-zones-btn');
  const modal = document.querySelector('#zones-modal');
  const closeBtn = document.querySelector('#close-zones-btn');
  const body = document.querySelector('#zones-modal-body');

  let loaded = false;

  btn?.addEventListener('click', async () => {
    modal.hidden = false;
    document.body.style.overflow = 'hidden';

    if (!loaded) {
      body.innerHTML = '<p style="color:#66747c;padding:20px 0">Загрузка...</p>';
      try {
        const res = await fetch('/static/prompts/jenks_zones.html');
        const html = await res.text();
        body.innerHTML = html;
        // Выполнить скрипты из загруженного HTML
        body.querySelectorAll('script').forEach(oldScript => {
          const newScript = document.createElement('script');
          if (oldScript.src) {
            newScript.src = oldScript.src;
          } else {
            newScript.textContent = oldScript.textContent;
          }
          document.body.appendChild(newScript);
        });
        loaded = true;
      } catch (e) {
        body.innerHTML = '<p style="color:#a33a1c">Не удалось загрузить виджет.</p>';
      }
    }
  });

  closeBtn?.addEventListener('click', closeModal);
  modal?.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !modal.hidden) closeModal();
  });

  function closeModal() {
    modal.hidden = true;
    document.body.style.overflow = '';
  }
})();
```

---

## Важные детали

- Виджет загружается **один раз** при первом открытии, потом кэшируется — повторные открытия мгновенные.
- Файл `jenks_zones.html` должен быть доступен по пути `/static/prompts/jenks_zones.html` — убедись что папка `prompts` внутри `static/` и файл туда скопирован.
- Закрытие модального окна — кнопка ×, клик на оверлей, или клавиша `Escape`.
- Данные для виджета (список участников, отставания) виджет содержит внутри себя — ничего дополнительно передавать не нужно.

---

## Что не менять

- Существующую разметку и стили блока `race-summary`
- Логику загрузки протокола
- Другие кнопки и элементы страницы
