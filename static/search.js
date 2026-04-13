/**
 * PharmaRef - Скрипт пошуку з автодоповненням
 */

(function() {
    'use strict';

    const MIN_QUERY_LENGTH = 3;
    const DEBOUNCE_DELAY = 300;

    let debounceTimer = null;
    let currentRequest = null;

    /**
     * Iнiцiалiзацiя автодоповнення
     */
    function initAutocomplete() {
        const searchInput = document.getElementById('search-input');
        const suggestionsContainer = document.getElementById('suggestions');

        if (!searchInput || !suggestionsContainer) {
            return;
        }

        // Обробка вводу
        searchInput.addEventListener('input', function(e) {
            const query = e.target.value.trim();

            // Скасовуємо попереднiй таймер
            if (debounceTimer) {
                clearTimeout(debounceTimer);
            }

            // Ховаємо пiдказки якщо запит короткий
            if (query.length < MIN_QUERY_LENGTH) {
                hideSuggestions();
                return;
            }

            // Затримка перед запитом
            debounceTimer = setTimeout(function() {
                fetchSuggestions(query);
            }, DEBOUNCE_DELAY);
        });

        // Закриття пiдказок при клiку поза ними
        document.addEventListener('click', function(e) {
            if (!searchInput.contains(e.target) && !suggestionsContainer.contains(e.target)) {
                hideSuggestions();
            }
        });

        // Навiгацiя клавiатурою
        searchInput.addEventListener('keydown', function(e) {
            const items = suggestionsContainer.querySelectorAll('.suggestion-item');
            const activeItem = suggestionsContainer.querySelector('.suggestion-item.active');
            let activeIndex = -1;

            if (activeItem) {
                activeIndex = Array.from(items).indexOf(activeItem);
            }

            switch(e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    if (activeIndex < items.length - 1) {
                        setActiveItem(items, activeIndex + 1);
                    }
                    break;

                case 'ArrowUp':
                    e.preventDefault();
                    if (activeIndex > 0) {
                        setActiveItem(items, activeIndex - 1);
                    }
                    break;

                case 'Enter':
                    if (activeItem) {
                        e.preventDefault();
                        selectSuggestion(activeItem.textContent);
                    }
                    break;

                case 'Escape':
                    hideSuggestions();
                    break;
            }
        });
    }

    /**
     * Запит пiдказок з API
     */
    function fetchSuggestions(query) {
        // Скасовуємо попереднiй запит
        if (currentRequest) {
            currentRequest.abort();
        }

        const controller = new AbortController();
        currentRequest = controller;

        fetch('/api/suggest?q=' + encodeURIComponent(query), {
            signal: controller.signal
        })
        .then(function(response) {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(function(suggestions) {
            if (suggestions && suggestions.length > 0) {
                showSuggestions(suggestions);
            } else {
                hideSuggestions();
            }
        })
        .catch(function(error) {
            if (error.name !== 'AbortError') {
                console.error('Помилка отримання пiдказок:', error);
            }
        })
        .finally(function() {
            currentRequest = null;
        });
    }

    /**
     * Показати пiдказки
     */
    function showSuggestions(suggestions) {
        const container = document.getElementById('suggestions');
        if (!container) return;

        container.innerHTML = '';

        suggestions.forEach(function(suggestion) {
            const item = document.createElement('div');
            item.className = 'suggestion-item';
            item.textContent = suggestion;

            item.addEventListener('click', function() {
                selectSuggestion(suggestion);
            });

            item.addEventListener('mouseenter', function() {
                const items = container.querySelectorAll('.suggestion-item');
                items.forEach(function(i) { i.classList.remove('active'); });
                item.classList.add('active');
            });

            container.appendChild(item);
        });

        container.classList.add('active');
    }

    /**
     * Сховати пiдказки
     */
    function hideSuggestions() {
        const container = document.getElementById('suggestions');
        if (container) {
            container.classList.remove('active');
            container.innerHTML = '';
        }
    }

    /**
     * Вибрати пiдказку
     */
    function selectSuggestion(value) {
        const searchInput = document.getElementById('search-input');
        if (searchInput) {
            searchInput.value = value;
            hideSuggestions();
            // Опцiонально: автоматично надсилаємо форму
            // searchInput.closest('form').submit();
        }
    }

    /**
     * Встановити активний елемент
     */
    function setActiveItem(items, index) {
        items.forEach(function(item) { item.classList.remove('active'); });
        if (items[index]) {
            items[index].classList.add('active');
            items[index].scrollIntoView({ block: 'nearest' });
        }
    }

    // Iнiцiалiзацiя при завантаженнi сторiнки
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAutocomplete);
    } else {
        initAutocomplete();
    }
})();
