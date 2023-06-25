'''
Text Input
==========

.. versionadded:: 1.0.4

.. image:: images/textinput-mono.jpg
.. image:: images/textinput-multi.jpg

The :class:`TextInput` widget provides a box for editable plain text.

Unicode, multiline, cursor navigation, selection and clipboard features
are supported.

The :class:`TextInput` uses two different coordinate systems:

* (x, y) - coordinates in pixels, mostly used for rendering on screen.
* (col, row) - cursor index in characters / lines, used for selection
  and cursor movement.


Usage example
-------------

To create a multiline :class:`TextInput` (the 'enter' key adds a new line)::

    from kivy.uix.textinput import TextInput
    textinput = TextInput(text='Hello world')

To create a singleline :class:`TextInput`, set the :class:`TextInput.multiline`
property to False (the 'enter' key will defocus the TextInput and emit an
:meth:`TextInput.on_text_validate` event)::

    def on_enter(instance, value):
        print('User pressed enter in', instance)

    textinput = TextInput(text='Hello world', multiline=False)
    textinput.bind(on_text_validate=on_enter)

The textinput's text is stored in its :attr:`TextInput.text` property. To run a
callback when the text changes::

    def on_text(instance, value):
        print('The widget', instance, 'have:', value)

    textinput = TextInput()
    textinput.bind(text=on_text)

You can set the :class:`focus <kivy.uix.behaviors.FocusBehavior>` to a
Textinput, meaning that the input box will be highlighted and keyboard focus
will be requested::

    textinput = TextInput(focus=True)

The textinput is defocused if the 'escape' key is pressed, or if another
widget requests the keyboard. You can bind a callback to the focus property to
get notified of focus changes::

    def on_focus(instance, value):
        if value:
            print('User focused', instance)
        else:
            print('User defocused', instance)

    textinput = TextInput()
    textinput.bind(focus=on_focus)

See :class:`~kivy.uix.behaviors.FocusBehavior`, from which the
:class:`TextInput` inherits, for more details.


Selection
---------

The selection is automatically updated when the cursor position changes.
You can get the currently selected text from the
:attr:`TextInput.selection_text` property.

Handles
-------

One can enable :attr:`TextInput.use_handles` property to enable or disable
the usage of selection handles. This property is True by default on mobiles.

Selection Handles uses the class :class:`Selector` as the base class for
the selection handles. You can customize the color for selection handles
like so ::

    <Selector>
        color: 0, 1, 0, 1
        # or <Textinput_instance>.selection_color or app.selection_color

TextInput instantiates the selection handles and stores it in the following
properties. :attr:`TextInput._handle_middle`,
:attr:`TextInput._handle_left`, :attr:`TextInput._handle_right`.

You should set the selection template before the Instantiating TextInput,
so as to get the selection handles to take the changes you set to apply.

Filtering
---------

You can control which text can be added to the :class:`TextInput` by
overwriting :meth:`TextInput.insert_text`. Every string that is typed, pasted
or inserted by any other means into the :class:`TextInput` is passed through
this function. By overwriting it you can reject or change unwanted characters.

For example, to write only in capitalized characters::

    class CapitalInput(TextInput):

        def insert_text(self, substring):
            s = substring.upper()
            return super().insert_text(s)

Or to only allow floats (0 - 9 and a single period)::

    class FloatInput(TextInput):

        pat = re.compile('[^0-9]')
        def insert_text(self, substring):
            pat = self.pat
            if '.' in self.text:
                s = re.sub(pat, '', substring)
            else:
                s = '.'.join(
                    re.sub(pat, '', s)
                    for s in substring.split('.', 1)
                )
            return super().insert_text(s)

Default shortcuts
-----------------

=============== ========================================================
   Shortcuts    Description
--------------- --------------------------------------------------------
Left            Move cursor to left
Right           Move cursor to right
Up              Move cursor to up
Down            Move cursor to down
Home            Move cursor at the beginning of the line
End             Move cursor at the end of the line
PageUp          Move cursor to 3 lines before
PageDown        Move cursor to 3 lines after
Backspace       Delete the selection or character before the cursor
Del             Delete the selection of character after the cursor
Shift + <dir>   Start a text selection. Dir can be Up, Down, Left or
                Right
Control + c     Copy selection
Control + x     Cut selection
Control + v     Paste clipboard content
Control + a     Select all the content
Control + z     undo
Control + r     redo
=============== ========================================================

.. note::
    To enable Emacs-style keyboard shortcuts, you can use
    :class:`~kivy.uix.behaviors.emacs.EmacsBehavior`.

'''


import re
import math
from os import environ
from weakref import ref
from itertools import chain, islice
import difflib
from bisect import bisect_left

from kivy.animation import Animation
from kivy.base import EventLoop
from kivy.cache import Cache
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window
from kivy.metrics import inch
from kivy.utils import boundary, platform
from kivy.uix.behaviors import FocusBehavior

from kivy.core.text import Label, DEFAULT_FONT
from kivy.core.textinput import TextInput as CoreTextInput
from kivy.graphics import Color, Rectangle, PushMatrix, PopMatrix, Callback
from kivy.graphics.context_instructions import Transform
from kivy.graphics.texture import Texture

from kivy.uix.widget import Widget
from kivy.uix.bubble import Bubble
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.image import Image

from kivy.logger import Logger

from kivy.properties import StringProperty, NumericProperty, \
    BooleanProperty, AliasProperty, OptionProperty, \
    ListProperty, ObjectProperty, VariableListProperty, ColorProperty, \
    BoundedNumericProperty

__all__ = ('TextInput', )


if 'KIVY_DOC' in environ:
    def triggered(*_, **__):
        def decorator_func(func):
            def decorated_func(*args, **kwargs):
                return func(*args, **kwargs)
            return decorated_func
        return decorator_func
else:
    from kivy.clock import triggered


Cache_register = Cache.register
Cache_append = Cache.append
Cache_get = Cache.get
Cache_remove = Cache.remove
Cache_register('textinput.label', timeout=60.)
Cache_register('textinput.width', timeout=60.)

FL_IS_LINEBREAK = 0x01
FL_IS_WORDBREAK = 0x02
FL_IS_NEWLINE = FL_IS_LINEBREAK | FL_IS_WORDBREAK

# late binding
Clipboard = None
CutBuffer = None
MarkupLabel = None

# for reloading, we need to keep a list of textinput to retrigger the rendering
_textinput_list = []

# When we are generating documentation, Config doesn't exist
_is_desktop = False
_scroll_timeout = _scroll_distance = 0
if Config:
    _is_desktop = Config.getboolean('kivy', 'desktop')
    _scroll_timeout = Config.getint('widgets', 'scroll_timeout')
    _scroll_distance = '{}sp'.format(Config.getint('widgets',
                                                   'scroll_distance'))

# register an observer to clear the textinput cache when OpenGL will reload
if 'KIVY_DOC' not in environ:

    def _textinput_clear_cache(*l):
        Cache_remove('textinput.label')
        Cache_remove('textinput.width')
        for wr in _textinput_list[:]:
            textinput = wr()
            if textinput is None:
                _textinput_list.remove(wr)
            else:
                textinput._trigger_refresh_text()
                textinput._refresh_hint_text()

    from kivy.graphics.context import get_context
    get_context().add_reload_observer(_textinput_clear_cache, True)


class Selector(ButtonBehavior, Image):
    '''Default template for the selection Handles

    In order to customize the look of the Selection Handles,
    you should adjust its template like so ::

        <Selector>
            color: 1, 0, 1, 1
    '''

    window = ObjectProperty()
    target = ObjectProperty()
    matrix = ObjectProperty()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.always_release = True
        self.matrix = self.target.get_window_matrix()

        with self.canvas.before:
            Callback(self.update_transform)
            PushMatrix()
            self.transform = Transform()

        with self.canvas.after:
            PopMatrix()

    def update_transform(self, cb):
        matrix = self.target.get_window_matrix()
        if self.matrix != matrix:
            self.matrix = matrix
            self.transform.identity()
            self.transform.transform(self.matrix)

    def transform_touch(self, touch):
        matrix = self.matrix.inverse()
        touch.apply_transform_2d(
            lambda x, y: matrix.transform_point(x, y, 0)[:2]
        )

    def on_touch_down(self, touch):
        if self.parent is not EventLoop.window:
            return

        try:
            touch.push()
            self.transform_touch(touch)
            self._touch_diff = self.top - touch.y
            if self.collide_point(*touch.pos):
                FocusBehavior.ignored_touch.append(touch)
            return super().on_touch_down(touch)
        finally:
            touch.pop()


class TextInputCutCopyPaste(Bubble):
    # Internal class used for showing the little bubble popup when
    # copy/cut/paste happen.

    textinput = ObjectProperty(None)
    ''' Holds a reference to the TextInput this Bubble belongs to.
    '''

    but_cut = ObjectProperty(None)
    but_copy = ObjectProperty(None)
    but_paste = ObjectProperty(None)
    but_selectall = ObjectProperty(None)

    matrix = ObjectProperty(None)

    _check_parent_ev = None

    def __init__(self, **kwargs):
        self.mode = 'normal'
        super().__init__(**kwargs)
        self._check_parent_ev = Clock.schedule_interval(self._check_parent, .5)
        self.matrix = self.textinput.get_window_matrix()

        with self.canvas.before:
            Callback(self.update_transform)
            PushMatrix()
            self.transform = Transform()

        with self.canvas.after:
            PopMatrix()

    def update_transform(self, cb):
        m = self.textinput.get_window_matrix()
        if self.matrix != m:
            self.matrix = m
            self.transform.identity()
            self.transform.transform(self.matrix)

    def transform_touch(self, touch):
        matrix = self.matrix.inverse()
        touch.apply_transform_2d(
            lambda x, y: matrix.transform_point(x, y, 0)[:2])

    def on_touch_down(self, touch):
        try:
            touch.push()
            self.transform_touch(touch)
            if self.collide_point(*touch.pos):
                FocusBehavior.ignored_touch.append(touch)
            return super().on_touch_down(touch)
        finally:
            touch.pop()

    def on_touch_up(self, touch):
        try:
            touch.push()
            self.transform_touch(touch)
            for child in self.content.children:
                if ref(child) in touch.grab_list:
                    touch.grab_current = child
                    break
            return super().on_touch_up(touch)
        finally:
            touch.pop()

    def on_textinput(self, instance, value):
        global Clipboard
        if value and not Clipboard and not _is_desktop:
            value._ensure_clipboard()

    def _check_parent(self, dt):
        # this is a prevention to get the Bubble staying on the screen, if the
        # attached textinput is not on the screen anymore.
        parent = self.textinput
        while parent is not None:
            if parent == parent.parent:
                break
            parent = parent.parent
        if parent is None:
            self._check_parent_ev.cancel()
            if self.textinput:
                self.textinput._hide_cut_copy_paste()

    def on_parent(self, instance, value):
        parent = self.textinput
        mode = self.mode

        if parent:
            self.content.clear_widgets()
            if mode == 'paste':
                # show only paste on long touch
                self.but_selectall.opacity = 1
                widget_list = [self.but_selectall, ]
                if not parent.readonly:
                    widget_list.append(self.but_paste)
            elif parent.readonly:
                # show only copy for read only text input
                widget_list = (self.but_copy, )
            else:
                # normal mode
                widget_list = (self.but_cut, self.but_copy, self.but_paste)

            for widget in widget_list:
                self.content.add_widget(widget)

    def do(self, action):
        textinput = self.textinput

        if action == 'cut':
            textinput.cut()
        elif action == 'copy':
            textinput.copy()
        elif action == 'paste':
            textinput.paste()
        elif action == 'selectall':
            textinput.select_all()
            self.mode = ''
            anim = Animation(opacity=0, d=.333)
            anim.bind(on_complete=lambda *args:
                      self.on_parent(self, self.parent))
            anim.start(self.but_selectall)
            return

        self.hide()

    def hide(self):
        parent = self.parent
        if not parent:
            return

        anim = Animation(opacity=0, d=.225)
        anim.bind(on_complete=lambda *args: parent.remove_widget(self))
        anim.start(self)


class TextInput(FocusBehavior, Widget):
    '''TextInput class. See module documentation for more information.

    :Events:
        `on_text_validate`
            Fired only in multiline=False mode when the user hits 'enter'.
            This will also unfocus the textinput.
        `on_double_tap`
            Fired when a double tap happens in the text input. The default
            behavior selects the text around the cursor position. More info at
            :meth:`on_double_tap`.
        `on_triple_tap`
            Fired when a triple tap happens in the text input. The default
            behavior selects the line around the cursor position. More info at
            :meth:`on_triple_tap`.
        `on_quad_touch`
            Fired when four fingers are touching the text input. The default
            behavior selects the whole text. More info at
            :meth:`on_quad_touch`.

    .. warning::
        When changing a :class:`TextInput` property that requires re-drawing,
        e.g. modifying the :attr:`text`, the updates occur on the next
        clock cycle and not instantly. This might cause any changes to the
        :class:`TextInput` that occur between the modification and the next
        cycle to be ignored, or to use previous values. For example, after
        a update to the :attr:`text`, changing the cursor in the same clock
        frame will move it using the previous text and will likely end up in an
        incorrect position. The solution is to schedule any updates to occur
        on the next clock cycle using
        :meth:`~kivy.clock.ClockBase.schedule_once`.

    .. Note::
        Selection is cancelled when TextInput is focused. If you need to
        show selection when TextInput is focused, you should delay
        (use Clock.schedule) the call to the functions for selecting
        text (select_all, select_text).

    .. versionchanged:: 1.10.0
        `background_disabled_active` has been removed.

    .. versionchanged:: 1.9.0

        :class:`TextInput` now inherits from
        :class:`~kivy.uix.behaviors.FocusBehavior`.
        :attr:`~kivy.uix.behaviors.FocusBehavior.keyboard_mode`,
        :meth:`~kivy.uix.behaviors.FocusBehavior.show_keyboard`,
        :meth:`~kivy.uix.behaviors.FocusBehavior.hide_keyboard`,
        :meth:`~kivy.uix.behaviors.FocusBehavior.focus`,
        and :attr:`~kivy.uix.behaviors.FocusBehavior.input_type`
        have been removed since they are now inherited
        from :class:`~kivy.uix.behaviors.FocusBehavior`.

    .. versionchanged:: 1.7.0
        `on_double_tap`, `on_triple_tap` and `on_quad_touch` events added.

    .. versionchanged:: 2.1.0
        :attr:`~kivy.uix.behaviors.FocusBehavior.keyboard_suggestions`
        is now inherited from :class:`~kivy.uix.behaviors.FocusBehavior`.
    '''

    keyboard_suggestions = BooleanProperty(True)
    '''If True provides auto suggestions on top of keyboard.
    This will only work if :attr:`input_type` is set to `text`, `url`, `mail` or
    `address`.

    .. warning::
        On Android, `keyboard_suggestions` relies on
        `InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS` to work, but some keyboards
        just ignore this flag. If you want to disable suggestions at all on
        Android, you can set `input_type` to `null`, which will request the
        input method to run in a limited "generate key events" mode.

    .. versionadded:: 2.1.0

    :attr:`keyboard_suggestions` is a :class:`~kivy.properties.BooleanProperty`
    and defaults to True
    '''

    def _set_on_input_type(self, instance, value):
        self._textinput.input_type = value

    input_type = OptionProperty('null', options=('null', 'text', 'number',
                                                 'url', 'mail', 'datetime',
                                                 'tel', 'address'))
    '''The kind of input keyboard to request.

    .. versionadded:: 1.8.0

    .. versionchanged:: 2.1.0
        Changed default value from `text` to `null`. Added `null` to options.

        .. warning::
            As the default value has been changed, you may need to adjust
            `input_type` in your code.

    :attr:`input_type` is an :class:`~kivy.properties.OptionsProperty` and
    defaults to 'null'. Can be one of 'null', 'text', 'number', 'url', 'mail',
    'datetime', 'tel' or 'address'.
    '''

    __events__ = ('on_text_validate', 'on_double_tap', 'on_triple_tap',
                  'on_quad_touch')

    _resolved_base_dir = None

    def __init__(self, **kwargs):
        self._update_graphics_ev = Clock.create_trigger(
            self._update_graphics, -1)
        self.is_focusable = kwargs.get('is_focusable', True)
        self.focus_provider = "external"
        self._cursor = [0, 0]
        self._selection = False
        self._selection_finished = True
        self._selection_touch = None
        # self.selection_text = u''
        self._selection_from = None
        self._selection_to = None
        self._selection_callback = None
        self._handle_left = None
        self._handle_right = None
        self._handle_middle = None
        self._bubble = None
        self._lines_flags = []
        self._lines_labels = []
        self._lines_rects = []
        self._lines_indexes = []
        self._hint_text_flags = []
        self._hint_text_labels = []
        self._hint_text_rects = []
        self._label_cached = None
        self._line_options = None
        self._keyboard_mode = Config.get('kivy', 'keyboard_mode')
        self._touch_count = 0
        self._refresh_text_from_property_ev = None
        self._long_touch_ev = None
        self._do_blink_cursor_ev = Clock.create_trigger(
            self._do_blink_cursor, .5, interval=True)
        self._refresh_line_options_ev = None
        self._scroll_distance_x = 0
        self._scroll_distance_y = 0
        self._enable_scroll = True
        self._have_scrolled = False
        self._rendered_text = ""
        self._current_text = ""

        # [from; to) range of lines being partially or fully rendered
        # in TextInput's viewport
        self._visible_lines_range = 0, 0

        self._textinput = CoreTextInput(target=self, validator=self.validator)
        self._textinput.bind(
            on_text_changed=self._handle_coretextinput_text_changed,
        )

        super().__init__(**kwargs)

        fbind = self.fbind
        refresh_line_options = self._trigger_refresh_line_options
        update_text_options = self._update_text_options
        trigger_update_graphics = self._trigger_update_graphics

        fbind('font_size', refresh_line_options)
        fbind('font_name', refresh_line_options)
        fbind('font_context', refresh_line_options)
        fbind('font_family', refresh_line_options)
        fbind('base_direction', refresh_line_options)
        fbind('text_language', refresh_line_options)

        def handle_readonly(instance, value):
            if value and (not _is_desktop):
                self.is_focusable = False
            if (not (value or self.disabled) or _is_desktop and
                    self._keyboard_mode == 'system'):
                self._editable = True
            else:
                self._editable = False

        fbind('padding', update_text_options)
        fbind('tab_width', update_text_options)
        fbind('font_size', update_text_options)
        fbind('font_name', update_text_options)
        fbind('size', update_text_options)
        fbind('password', update_text_options)
        fbind('password_mask', update_text_options)

        fbind('pos', trigger_update_graphics)
        fbind('halign', trigger_update_graphics)
        fbind('readonly', handle_readonly)
        fbind('focus', self._on_textinput_focused)
        fbind('input_type', self._set_on_input_type)
        handle_readonly(self, self.readonly)

        handles = self._trigger_position_handles = Clock.create_trigger(
            self._position_handles)
        self._trigger_show_handles = Clock.create_trigger(
            self._show_handles, .05)
        self._trigger_cursor_reset = Clock.create_trigger(
            self._reset_cursor_blink)
        self._trigger_update_cutbuffer = Clock.create_trigger(
            self._update_cutbuffer)
        refresh_line_options()
        self._trigger_refresh_text()

        fbind('pos', handles)
        fbind('size', handles)

        # when the gl context is reloaded, trigger the text rendering again.
        _textinput_list.append(ref(self, TextInput._reload_remove_observer))

        if platform == 'linux':
            self._ensure_clipboard()

    def validator(self, substring: str) -> bool:
        '''The validator function used for input validation. If the function
        returns False, the input will be rejected on the underlying textinput
        implementation.

        The user can override this function to customize the validation
        behavior.
        '''
        if substring == "\n" and not self.multiline:
            return False

        if substring == "\t" and not self.write_tab:
            return False

        return True


    def on_text_validate(self):
        pass

    def cursor_index(self, cursor=None):
        '''Return the cursor index in the text/value.
        '''
        if not cursor:
            cursor = self.cursor
        try:
            lines = self._lines
            if not lines:
                return 0

            flags = self._lines_flags
            index, cursor_row = cursor

            for _, line, flag in zip(
                range(min(cursor_row, len(lines))),
                lines,
                flags
            ):
                index += len(line)
                if flag & FL_IS_LINEBREAK:
                    index += 1

            if flags[cursor_row] & FL_IS_LINEBREAK:
                index += 1
            return index

        except IndexError:
            return 0

    def cursor_offset(self):
        '''Get the cursor x offset on the current line.
        '''
        offset = 0
        row = int(self.cursor_row)
        col = int(self.cursor_col)
        lines = self._lines
        if col and row < len(lines):
            offset = self._get_text_width(
                lines[row][:col],
                self.tab_width,
                self._label_cached
            )
        return offset

    def get_cursor_from_index(self, index):
        '''Return the (col, row) of the cursor from text index.
        '''
        index = boundary(index, 0, len(self._current_text))
        if index <= 0:
            return 0, 0
        flags = self._lines_flags
        lines = self._lines
        if not lines:
            return 0, 0

        i = 0
        for row, line in enumerate(lines):
            count = i + len(line)
            if flags[row] & FL_IS_LINEBREAK:
                count += 1
                i += 1
            if count >= index:
                return index - i, row
            i = count
        return int(index), int(row)

    def select_text(self, start, end):
        ''' Select a portion of text displayed in this TextInput.

        .. versionadded:: 1.4.0

        :Parameters:
            `start`
                Index of textinput.text from where to start selection
            `end`
                Index of textinput.text till which the selection should be
                displayed
        '''
        if end < start:
            raise Exception('end must be superior to start')
        text_length = len(self._current_text)
        self._selection_from = boundary(start, 0, text_length)
        self._selection_to = boundary(end, 0, text_length)
        self._selection_finished = True
        self._update_selection(True)
        self._update_graphics_selection()

    def select_all(self):
        ''' Select all of the text displayed in this TextInput.

        .. versionadded:: 1.4.0
        '''
        self.select_text(0, len(self._current_text))

    re_indent = re.compile(r'^(\s*|)')

    def _auto_indent(self, substring):
        # FIXME: We need to handle it.
        index = self.cursor_index()
        if index > 0:
            _text = self._current_text
            line_start = _text.rfind('\n', 0, index)
            if line_start > -1:
                line = _text[line_start + 1:index]
                indent = self.re_indent.match(line).group()
                substring += indent
        return substring

    def _handle_coretextinput_text_changed(
        self, instance, substring, start_index=None, end_index=None
    ):
        # The core textinput has changed its text.
        # We need to update the textinput.
        self.replace_text(substring, start_index, end_index)

    def _handle_coretextinput_selection_changed(
        self, instance, start, end
    ):
        # The core textinput has changed its selection.
        # We need to update the textinput.
        self.select_text(start, end)

        if start == end:
            self.cursor = self.get_cursor_from_index(start)

    def replace_text(self, substring, start_index=None, end_index=None, move_cursor_at_end=True):
        '''Replace the current text with the new substring. If start_index and
        end_index are not specified, the whole text will be replaced.

        At the end of the operation, the cursor will be moved to the end of
        the new text, otherwise it will be moved to the end of the whole text.

        If start_index > end_index, the text between end_index and start_index
        will be deleted, and the cursor will be moved at end_index.

        '''

        if isinstance(substring, bytes):
            substring = substring.decode('utf8')

        if start_index is None:
            # If start_index is not specified, we assume that
            # the text will be replaced from the beginning.
            start_index = 0

        if end_index is None:
            # If end_index is not specified, we assume that
            # the text will be replaced to the end.
            end_index = len(self._current_text)

        # We should consider when start_index > end_index.
        lenght = abs(start_index - end_index)

        _tmptext = "" + self._current_text

        Logger.debug("Textinput: replace__before " + _tmptext)
        _tmptext = _tmptext[:start_index] + substring + _tmptext[start_index+lenght:]
        Logger.debug("Textinput: replace__after " + _tmptext)

        if self._current_text == _tmptext:
            # If the text is not changed, we don't need to do anything.
            Logger.debug("Textinput: replace__same")
            return

        self._current_text = _tmptext

        self._refresh_text(self._current_text, requestor="textinput")
        if move_cursor_at_end:
            self.cursor = self.get_cursor_from_index(end_index)

    def insert_text(self, substring):
        '''Insert new text at the current cursor position. Override this
        function in order to pre-process text for input validation.
        '''
        # FIXME: We need to handle it.
        raise NotImplementedError

    def reset_undo(self):
        '''Reset undo and redo lists from memory.

        .. versionadded:: 1.3.0

        '''
        # FIXME: reset_undo is not implemented in core textinput
        self._textinput.reset_undo()

    def do_redo(self):
        '''Do redo operation.

        .. versionadded:: 1.3.0

        This action re-does any command that has been un-done by
        do_undo/ctrl+z. This function is automatically called when
        `ctrl+r` keys are pressed.
        '''
        self._textinput.redo()

    def do_undo(self):
        '''Do undo operation.

        .. versionadded:: 1.3.0

        This action un-does any edits that have been made since the last
        call to reset_undo().
        This function is automatically called when `ctrl+z` keys are pressed.
        '''
        self._textinput.undo()

    def do_backspace(self):
        '''Do backspace operation from the current cursor position.
        This action might do several things:

            - removing the current selection if available.
            - removing the previous char and move the cursor back.
            - do nothing, if we are at the start.

        '''
        if self.readonly:
            return
        # FIXME: backspace is not implemented in core textinput
        self._textinput.backspace()

    _re_whitespace = re.compile(r'\s+')

    def _move_cursor_word_left(self, index=None):
        # FIXME: Not tested as we need to implement control in action handler in core textinput
        pos = index or self.cursor_index()
        if pos == 0:
            return self.cursor
        lines = self._lines
        col, row = self.get_cursor_from_index(pos)
        if col == 0:
            row -= 1
            col = len(lines[row])

        while True:
            matches = list(self._re_whitespace.finditer(lines[row], 0, col))
            if not matches:
                if col == 0:
                    if row == 0:
                        return 0, 0
                    row -= 1
                    col = len(lines[row])
                    continue
                return 0, row

            match = matches[-1]
            mpos = match.end()
            if mpos == col:
                if len(matches) > 1:
                    match = matches[-2]
                    mpos = match.end()
                else:
                    if match.start() == 0:
                        if row == 0:
                            return 0, 0
                        row -= 1
                        col = len(lines[row])
                        continue
                    return 0, row
            col = mpos
            return col, row

    def _move_cursor_word_right(self, index=None):
        # FIXME: Not tested as we need to implement control in action handler in core textinput
        pos = index or self.cursor_index()
        col, row = self.get_cursor_from_index(pos)
        lines = self._lines
        mrow = len(lines) - 1
        if row == mrow and col == len(lines[row]):
            return col, row
        if col == len(lines[row]):
            row += 1
            col = 0

        while True:
            matches = list(self._re_whitespace.finditer(lines[row], col))
            if not matches:
                if col == len(lines[row]):
                    if row == mrow:
                        return col, row
                    row += 1
                    col = 0
                    continue
                return len(lines[row]), row

            match = matches[0]
            mpos = match.start()
            if mpos == col:
                if len(matches) > 1:
                    match = matches[1]
                    mpos = match.start()
                else:
                    if match.end() == len(lines[row]):
                        if row == mrow:
                            return col, row
                        row += 1
                        col = 0
                        continue
                    return len(lines[row]), row
            col = mpos
            return col, row

    def _expand_range(self, ifrom, ito=None):
        if ito is None:
            ito = ifrom
        rfrom = self.get_cursor_from_index(ifrom)[1]
        rtcol, rto = self.get_cursor_from_index(ito)
        rfrom, rto = self._expand_rows(rfrom, rto + 1 if rtcol else rto)

        return (self.cursor_index((0, rfrom)),
                self.cursor_index((0, rto)))

    def _expand_rows(self, rfrom, rto=None):
        if rto is None or rto == rfrom:
            rto = rfrom + 1
        lines = self._lines
        flags = list(reversed(self._lines_flags))
        while rfrom > 0 and not (flags[rfrom - 1] & FL_IS_NEWLINE):
            rfrom -= 1
        rmax = len(lines) - 1
        while 0 < rto < rmax and not (flags[rto - 1] & FL_IS_NEWLINE):
            rto += 1
        return max(0, rfrom), min(rmax, rto)

    @property
    def pgmove_speed(self):
        """how much vertical distance hitting pg_up or pg_down will move
        """
        return int(
            self.height
            / (self.line_height + self.line_spacing) - 1
        )

    def _move_cursor_up(self, col, row, control=False, alt=False):
        if self.multiline and control:
            self.scroll_y = max(0, self.scroll_y - self.line_height)
        elif not self.readonly and self.multiline and alt:
            # self._shift_lines(-1)
            # FIXME: We need to implement _shift_lines again.
            return
        else:
            row = max(row - 1, 0)
            col = min(len(self._lines[row]), col)

        return col, row

    def _move_cursor_down(self, col, row, control, alt):
        if self.multiline and control:
            maxy = self.minimum_height - self.height
            self.scroll_y = max(
                0,
                min(maxy, self.scroll_y + self.line_height)
            )
        elif not self.readonly and self.multiline and alt:
            # self._shift_lines(1)
            # FIXME: We need to implement _shift_lines again.
            return
        else:
            row = min(row + 1, len(self._lines) - 1)
            col = min(len(self._lines[row]), col)

        return col, row

    def do_cursor_movement(self, action, control=False, alt=False):
        '''Move the cursor relative to its current position.
        Action can be one of :

            - cursor_left: move the cursor to the left
            - cursor_right: move the cursor to the right
            - cursor_up: move the cursor on the previous line
            - cursor_down: move the cursor on the next line
            - cursor_home: move the cursor at the start of the current line
            - cursor_end: move the cursor at the end of current line
            - cursor_pgup: move one "page" before
            - cursor_pgdown: move one "page" after

        In addition, the behavior of certain actions can be modified:

            - control + cursor_left: move the cursor one word to the left
            - control + cursor_right: move the cursor one word to the right
            - control + cursor_up: scroll up one line
            - control + cursor_down: scroll down one line
            - control + cursor_home: go to beginning of text
            - control + cursor_end: go to end of text
            - alt + cursor_up: shift line(s) up
            - alt + cursor_down: shift line(s) down

        .. versionchanged:: 1.9.1

        '''
        if not self._lines:
            return

        col, row = self.cursor
        if action == 'cursor_up':
            result = self._move_cursor_up(col, row, control, alt)
            if result:
                col, row = result
            else:
                return

        elif action == 'cursor_down':
            result = self._move_cursor_down(col, row, control, alt)
            if result:
                col, row = result
            else:
                return

        elif action == 'cursor_home':
            col = 0
            if control:
                row = 0

        elif action == 'cursor_end':
            if control:
                row = len(self._lines) - 1
            col = len(self._lines[row])

        elif action == 'cursor_pgup':
            row = max(0, row - self.pgmove_speed)
            col = min(len(self._lines[row]), col)

        elif action == 'cursor_pgdown':
            row = min(row + self.pgmove_speed, len(self._lines) - 1)
            col = min(len(self._lines[row]), col)

        elif (
            self._selection and self._selection_finished
            and self._selection_from < self._selection_to
            and action == 'cursor_left'
        ):
            current_selection_to = self._selection_to
            while self._selection_from != current_selection_to:
                current_selection_to -= 1
                if col:
                    col -= 1
                else:
                    row -= 1
                    col = len(self._lines[row])

        elif (
            self._selection and self._selection_finished
            and self._selection_from > self._selection_to
            and action == 'cursor_right'
        ):
            current_selection_to = self._selection_to
            while self._selection_from != current_selection_to:
                current_selection_to += 1
                if len(self._lines[row]) > col:
                    col += 1
                else:
                    row += 1
                    col = 0

        elif action == 'cursor_left':
            if not self.password and control:
                col, row = self._move_cursor_word_left()
            else:
                if col == 0:
                    if row:
                        row -= 1
                        col = len(self._lines[row])
                else:
                    col, row = col - 1, row

        elif action == 'cursor_right':
            if not self.password and control:
                col, row = self._move_cursor_word_right()
            else:
                if col == len(self._lines[row]):
                    if row < len(self._lines) - 1:
                        col = 0
                        row += 1
                else:
                    col, row = col + 1, row

        dont_move_cursor = control and action in ['cursor_up', 'cursor_down']
        if dont_move_cursor:
            self._trigger_update_graphics()
        else:
            self.cursor = col, row

    def get_cursor_from_xy(self, x, y):
        '''Return the (col, row) of the cursor from an (x, y) position.
        '''
        padding_left, padding_top, padding_right, padding_bottom = self.padding

        lines = self._lines
        dy = self.line_height + self.line_spacing
        cursor_x = x - self.x
        scroll_y = self.scroll_y
        scroll_x = self.scroll_x
        scroll_y = scroll_y / dy if scroll_y > 0 else 0

        cursor_y = (self.top - padding_top + scroll_y * dy) - y
        cursor_y = int(boundary(
            round(cursor_y / dy - 0.5),
            0,
            len(lines) - 1
        ))

        get_text_width = self._get_text_width
        tab_width = self.tab_width
        label_cached = self._label_cached

        # Offset for horizontal text alignment
        xoff = 0
        halign = self.halign
        base_dir = self.base_direction or self._resolved_base_dir
        auto_halign_r = halign == 'auto' and base_dir and 'rtl' in base_dir

        if halign == 'center':
            viewport_width = self.width - padding_left - padding_right
            xoff = max(
                0, int((viewport_width - self._get_row_width(cursor_y)) / 2)
            )

        elif halign == 'right' or auto_halign_r:
            viewport_width = self.width - padding_left - padding_right
            xoff = max(
                0, int(viewport_width - self._get_row_width(cursor_y))
            )

        for i in range(0, len(lines[cursor_y])):
            line_y = lines[cursor_y]

            if cursor_x + scroll_x < (
                xoff
                + get_text_width(line_y[:i], tab_width, label_cached)
                + get_text_width(line_y[i], tab_width, label_cached) * 0.6
                + padding_left
            ):
                cursor_x = i
                break
        else:
            cursor_x = len(lines[cursor_y])

        return cursor_x, cursor_y

    #
    # Selection control
    #
    def cancel_selection(self):
        '''Cancel current selection (if any).
        '''
        self._selection_from = self._selection_to = self.cursor_index()
        self._selection = False
        self._selection_finished = True
        self._selection_touch = None
        self._trigger_update_graphics()

    def delete_selection(self):
        '''Delete the current text selection (if any).
        '''
        # FIXME: call backspace in core textinput when available
        if self.readonly:
            return
        self._hide_handles(EventLoop.window)
        raise NotImplementedError

    def _update_selection(self, finished=False):
        '''Update selection text and order of from/to if finished is True.
        Can be called multiple times until finished is True.
        '''
        a, b = int(self._selection_from), int(self._selection_to)
        if a > b:
            a, b = b, a
        self._selection_finished = finished

        if not finished:
            self._selection = True
        else:
            self._selection = bool(b - a)
            self._selection_touch = None

        # Updates the selection also on the underlying TextInput provider
        self._textinput.select(a, b)

    #
    # Touch control
    #
    def long_touch(self, dt):
        self._long_touch_ev = None
        if self._selection_to == self._selection_from:
            pos = self.to_local(*self._touch_down.pos, relative=False)
            self._show_cut_copy_paste(
                pos, EventLoop.window, mode='paste')

    def cancel_long_touch_event(self):
        # schedule long touch for paste
        if self._long_touch_ev is not None:
            self._long_touch_ev.cancel()
            self._long_touch_ev = None

    def _select_word(self, delimiters=u' .,:;!?\'"<>()[]{}'):
        cindex = self.cursor_index()
        col = self.cursor_col
        line = self._lines[self.cursor_row]
        start = max(0, len(line[:col]) -
                    max(line[:col].rfind(s) for s in delimiters) - 1)
        end = min((line[col:].find(s) if line[col:].find(s) > -1
                   else (len(line) - col)) for s in delimiters)
        Clock.schedule_once(lambda dt: self.select_text(cindex - start,
                                                        cindex + end))

    def on_double_tap(self):
        '''This event is dispatched when a double tap happens
        inside TextInput. The default behavior is to select the
        word around the current cursor position. Override this to provide
        different behavior. Alternatively, you can bind to this
        event to provide additional functionality.
        '''
        self._select_word()

    def on_triple_tap(self):
        '''This event is dispatched when a triple tap happens
        inside TextInput. The default behavior is to select the
        line around current cursor position. Override this to provide
        different behavior. Alternatively, you can bind to this
        event to provide additional functionality.
        '''
        ci = self.cursor_index()
        sindex, eindex = self._expand_range(ci)
        Clock.schedule_once(lambda dt: self.select_text(sindex, eindex))

    def on_quad_touch(self):
        '''This event is dispatched when four fingers are touching
        inside TextInput. The default behavior is to select all text.
        Override this to provide different behavior. Alternatively,
        you can bind to this event to provide additional functionality.
        '''
        Clock.schedule_once(lambda dt: self.select_all())

    def on_touch_down(self, touch):
        if self.disabled:
            return

        touch_pos = touch.pos
        if not self.collide_point(*touch_pos):
            return False
        if super().on_touch_down(touch):
            return True

        if self.focus:
            self._trigger_cursor_reset()

        # Check for scroll wheel
        if 'button' in touch.profile and touch.button.startswith('scroll'):
            # TODO: implement 'scrollleft' and 'scrollright'
            scroll_type = touch.button[6:]
            if scroll_type == 'down':
                if self.multiline:
                    if self.scroll_y > 0:
                        self.scroll_y = max(0,
                                            self.scroll_y - self.line_height *
                                            self.lines_to_scroll)
                        self._trigger_update_graphics()
                else:
                    if self.scroll_x > 0:
                        self.scroll_x = max(0, self.scroll_x -
                                            self.line_height)
                        self._trigger_update_graphics()
            if scroll_type == 'up':
                if self.multiline:
                    max_scroll_y = max(0, self.minimum_height - self.height)
                    if self.scroll_y < max_scroll_y:
                        self.scroll_y = min(max_scroll_y,
                                            self.scroll_y + self.line_height *
                                            self.lines_to_scroll)
                        self._trigger_update_graphics()
                else:
                    minimum_width = (self._get_row_width(0) + self.padding[0] +
                                     self.padding[2])
                    max_scroll_x = max(0, minimum_width - self.width)
                    if self.scroll_x < max_scroll_x:
                        self.scroll_x = min(max_scroll_x, self.scroll_x +
                                            self.line_height)
                        self._trigger_update_graphics()
            return True

        touch.grab(self)
        self._touch_count += 1
        if touch.is_double_tap:
            self.dispatch('on_double_tap')
        if touch.is_triple_tap:
            self.dispatch('on_triple_tap')
        if self._touch_count == 4:
            self.dispatch('on_quad_touch')

        # stores the touch for later use
        self._touch_down = touch

        # Is a new touch_down, so previous scroll states needs to be reset
        self._enable_scroll = True
        self._have_scrolled = False
        self._scroll_distance_x = 0
        self._scroll_distance_y = 0

        self._hide_cut_copy_paste(EventLoop.window)
        # schedule long touch for paste
        self._long_touch_ev = Clock.schedule_once(self.long_touch, .5)

        self.cursor = self.get_cursor_from_xy(*touch_pos)
        if not self.scroll_from_swipe:
            self._cancel_update_selection(self._touch_down)

        if CutBuffer and 'button' in touch.profile and \
                touch.button == 'middle':
            self.insert_text(CutBuffer.get_cutbuffer())
            return True

        return True

    # cancel/update existing selection after a single tap
    def _cancel_update_selection(self, touch):
        if not self._selection_touch:
            self.cancel_selection()
            self._selection_touch = touch
            self._selection_from = self._selection_to = self.cursor_index()
            self._update_selection()

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return
        if not self.focus:
            touch.ungrab(self)
            if self._selection_touch is touch:
                self._selection_touch = None
            return False

        if self.scroll_from_swipe:
            self.scroll_text_from_swipe(touch)

        if not self._have_scrolled and self._selection_touch is touch:
            self.cursor = self.get_cursor_from_xy(touch.x, touch.y)
            self._selection_to = self.cursor_index()
            self._update_selection()
            return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return
        touch.ungrab(self)
        self._touch_count -= 1

        self.cancel_long_touch_event()

        if not self.focus:
            return False

        # types of touch that will have higher priority in being recognized,
        # compared to single tap
        prioritized_touch_types = (
            touch.is_double_tap
            or touch.is_triple_tap
            or self._touch_count == 4
        )

        if not self._have_scrolled and not prioritized_touch_types:
            # Is a single tap and did not scrolled.
            # Selection needs to be canceled.
            self._cancel_update_selection(self._touch_down)

        # show Bubble
        win = EventLoop.window
        if self._selection_to != self._selection_from:
            self._show_cut_copy_paste(touch.pos, win)

        if self._selection_touch is touch:
            self._selection_to = self.cursor_index()
            self._update_selection(True)
            if self.use_handles and self._selection_to == self._selection_from:
                self._hide_handles()
                handle_middle = self._handle_middle
                if handle_middle is None:
                    self._handle_middle = handle_middle = Selector(
                        source=self.handle_image_middle,
                        window=win,
                        target=self,
                        size_hint=(None, None),
                        size=('45dp', '45dp'))
                    handle_middle.bind(on_press=self._handle_pressed,
                                       on_touch_move=self._handle_move,
                                       on_release=self._handle_released)
                if not self._handle_middle.parent and self._current_text:
                    EventLoop.window.add_widget(handle_middle, canvas='after')
                self._position_handles(mode='middle')
            return True

    def scroll_text_from_swipe(self, touch):
        _scroll_timeout = (touch.time_update - touch.time_start) * 1000
        self._scroll_distance_x += abs(touch.dx)
        self._scroll_distance_y += abs(touch.dy)
        if not self._have_scrolled:
            # To be considered a scroll, touch should travel more than
            # scroll_distance in less than the scroll_timeout since touch_down
            if not (
                _scroll_timeout <= self.scroll_timeout
                and (
                    (self._scroll_distance_x >= self.scroll_distance)
                    or (self._scroll_distance_y >= self.scroll_distance)
                )
            ):
                # Distance isn't enough (yet) to consider it as a scroll
                if _scroll_timeout <= self.scroll_timeout:
                    # Timeout is not reached, scroll is still enabled.
                    return False
                else:
                    self._enable_scroll = False
                    self._cancel_update_selection(self._touch_down)
                    return False
            # We have a scroll!
            self._have_scrolled = True

        self.cancel_long_touch_event()

        if self.multiline:
            max_scroll_y = max(0, self.minimum_height - self.height)
            self.scroll_y = min(
                max(0, self.scroll_y + touch.dy),
                max_scroll_y
            )
        else:
            minimum_width = (
                self._get_row_width(0)
                + self.padding[0] + self.padding[2]
            )
            max_scroll_x = max(0, minimum_width - self.width)
            self.scroll_x = min(
                max(0, self.scroll_x - touch.dx),
                max_scroll_x
            )
        self._trigger_update_graphics()
        self._position_handles()
        return True

    def _handle_pressed(self, instance):
        self._hide_cut_copy_paste()
        from_, to_ = self._selection_from, self.selection_to
        if from_ > to_:
            self._selection_from, self._selection_to = to_, from_

    def _handle_released(self, instance):
        if self._selection_from == self.selection_to:
            return

        self._update_selection()
        self._show_cut_copy_paste(
            (
                self.x + instance.right
                if instance is self._handle_left
                else self.x + instance.x,
                self.y + instance.top + self.line_height
            ),
            EventLoop.window
        )

    def _handle_move(self, instance, touch):
        if touch.grab_current != instance:
            return
        get_cursor = self.get_cursor_from_xy
        handle_right = self._handle_right
        handle_left = self._handle_left
        handle_middle = self._handle_middle

        try:
            touch.push()
            touch.apply_transform_2d(self.to_widget)
            x, y = touch.pos
        finally:
            touch.pop()

        cursor = get_cursor(
            x,
            y + instance._touch_diff + (self.line_height / 2)
        )
        self.cursor = cursor

        if instance != touch.grab_current:
            return

        if instance == handle_middle:
            self._position_handles(mode='middle')
            return

        cindex = self.cursor_index()

        if instance == handle_left:
            self._selection_from = cindex
        elif instance == handle_right:
            self._selection_to = cindex
        self._update_selection()
        self._trigger_update_graphics()
        self._trigger_position_handles()

    def _position_handles(self, *args, **kwargs):
        if not self._current_text:
            return
        mode = kwargs.get('mode', 'both')

        lh = self.line_height

        handle_middle = self._handle_middle
        if handle_middle:
            hp_mid = self.cursor_pos
            pos = self.to_local(*hp_mid, relative=True)
            handle_middle.x = pos[0] - handle_middle.width / 2
            handle_middle.top = max(self.padding[3],
                                    min(self.height - self.padding[1],
                                        pos[1] - lh))
        if mode[0] == 'm':
            return

        group = self.canvas.get_group('selection')
        if not group:
            return

        EventLoop.window.remove_widget(self._handle_middle)

        handle_left = self._handle_left
        if not handle_left:
            return
        hp_left = group[2].pos
        handle_left.pos = self.to_local(*hp_left, relative=True)
        handle_left.x -= handle_left.width
        handle_left.y -= handle_left.height

        handle_right = self._handle_right
        last_rect = group[-1]
        hp_right = last_rect.pos[0], last_rect.pos[1]
        x, y = self.to_local(*hp_right, relative=True)
        handle_right.x = x + last_rect.size[0]
        handle_right.y = y - handle_right.height

    def _hide_handles(self, win=None):
        win = win or EventLoop.window
        if win is None:
            return
        win.remove_widget(self._handle_right)
        win.remove_widget(self._handle_left)
        win.remove_widget(self._handle_middle)

    def _show_handles(self, dt):
        if not self.use_handles or not self._current_text:
            return

        win = EventLoop.window

        handle_right = self._handle_right
        handle_left = self._handle_left
        if self._handle_left is None:
            self._handle_left = handle_left = Selector(
                source=self.handle_image_left,
                target=self,
                window=win,
                size_hint=(None, None),
                size=('45dp', '45dp'))
            handle_left.bind(on_press=self._handle_pressed,
                             on_touch_move=self._handle_move,
                             on_release=self._handle_released)
            self._handle_right = handle_right = Selector(
                source=self.handle_image_right,
                target=self,
                window=win,
                size_hint=(None, None),
                size=('45dp', '45dp'))
            handle_right.bind(on_press=self._handle_pressed,
                              on_touch_move=self._handle_move,
                              on_release=self._handle_released)
        else:
            if self._handle_left.parent:
                self._position_handles()
                return
            if not self.parent:
                return

        self._trigger_position_handles()
        if self.selection_from != self.selection_to:
            self._handle_left.opacity = self._handle_right.opacity = 0
            win.add_widget(self._handle_left, canvas='after')
            win.add_widget(self._handle_right, canvas='after')
            anim = Animation(opacity=1, d=.4)
            anim.start(self._handle_right)
            anim.start(self._handle_left)

    def _show_cut_copy_paste(
        self, pos, win, parent_changed=False, mode='', pos_in_window=False, *l
    ):
        """Show a bubble with cut copy and paste buttons"""
        if not self.use_bubble:
            return

        bubble = self._bubble
        if bubble is None:
            self._bubble = bubble = TextInputCutCopyPaste(textinput=self)
            self.fbind('parent', self._show_cut_copy_paste, pos, win, True)

            def hide_(*args):
                return self._hide_cut_copy_paste(win)

            self.bind(
                focus=hide_,
                cursor_pos=hide_,
            )
        else:
            win.remove_widget(bubble)
            if not self.parent:
                return
        if parent_changed:
            return

        # Search the position from the touch to the window
        lh, ls = self.line_height, self.line_spacing

        x, y = pos
        t_pos = (x, y) if pos_in_window else self.to_window(x, y)
        bubble_size = bubble.size
        bubble_hw = bubble_size[0] / 2.
        win_size = win.size
        bubble_pos = (t_pos[0], t_pos[1] + inch(.25))

        if (bubble_pos[0] - bubble_hw) < 0:
            # bubble beyond left of window
            if bubble_pos[1] > (win_size[1] - bubble_size[1]):
                # bubble above window height
                bubble_pos = (bubble_hw, (t_pos[1]) - (lh + ls + inch(.25)))
                bubble.arrow_pos = 'top_left'
            else:
                bubble_pos = (bubble_hw, bubble_pos[1])
                bubble.arrow_pos = 'bottom_left'
        elif (bubble_pos[0] + bubble_hw) > win_size[0]:
            # bubble beyond right of window
            if bubble_pos[1] > (win_size[1] - bubble_size[1]):
                # bubble above window height
                bubble_pos = (
                    win_size[0] - bubble_hw,
                    (t_pos[1]) - (lh + ls + inch(.25))
                )
                bubble.arrow_pos = 'top_right'
            else:
                bubble_pos = (win_size[0] - bubble_hw, bubble_pos[1])
                bubble.arrow_pos = 'bottom_right'
        else:
            if bubble_pos[1] > (win_size[1] - bubble_size[1]):
                # bubble above window height
                bubble_pos = (
                    bubble_pos[0],
                    (t_pos[1]) - (lh + ls + inch(.25))
                )
                bubble.arrow_pos = 'top_mid'
            else:
                bubble.arrow_pos = 'bottom_mid'

        bubble_pos = self.to_widget(*bubble_pos, relative=True)
        bubble.center_x = bubble_pos[0]
        if bubble.arrow_pos[0] == 't':
            bubble.top = bubble_pos[1]
        else:
            bubble.y = bubble_pos[1]
        bubble.mode = mode
        Animation.cancel_all(bubble)
        bubble.opacity = 0
        win.add_widget(bubble, canvas='after')
        Animation(opacity=1, d=.225).start(bubble)

    def _hide_cut_copy_paste(self, win=None):
        bubble = self._bubble
        if not bubble:
            return

        bubble.hide()

    #
    # Private
    #

    @staticmethod
    def _reload_remove_observer(wr):
        """called when the textinput is deleted"""
        if wr in _textinput_list:
            _textinput_list.remove(wr)

    def _on_textinput_focused(self, instance, value, *largs):
        win = EventLoop.window
        self.cancel_selection()
        self._hide_cut_copy_paste(win)

        if value:
            if (
                not (self.readonly or self.disabled)
                or _is_desktop
                and self._keyboard_mode == 'system'
            ):
                self._trigger_cursor_reset()
                self._editable = True
            else:
                self._editable = False
        else:
            self._do_blink_cursor_ev.cancel()
            self._hide_handles(win)

    def _enter_focused_mode(self):
        self._textinput.bind(
            on_focus=self._handle_coretextinput_focus,
            on_action=self._handle_coretextinput_action,
            on_shortcut=self._handle_coretextinput_shortcut,
            on_selection_changed=self._handle_coretextinput_selection_changed,
        )
        self._textinput.start()

        super()._enter_focused_mode()

    def _exit_focused_mode(self):
        self._textinput.unbind(
            on_focus=self._handle_coretextinput_focus,
            on_action=self._handle_coretextinput_action,
            on_shortcut=self._handle_coretextinput_shortcut,
            on_selection_changed=self._handle_coretextinput_selection_changed,
        )
        self._textinput.pause()

        super()._exit_focused_mode()

    def _ensure_clipboard(self):
        global Clipboard, CutBuffer
        if not Clipboard:
            from kivy.core.clipboard import Clipboard, CutBuffer

    def cut(self):
        ''' Copy current selection to clipboard then delete it from TextInput.

        .. versionadded:: 1.8.0

        '''

        self._ensure_clipboard()
        data = self._textinput.cut()
        Clipboard.copy(data)

    def copy(self, data=''):
        ''' Copy the value provided in argument `data` into current clipboard.
        If data is not of type string it will be converted to string.
        If no data is provided then current selection if present is copied.

        .. versionadded:: 1.8.0

        '''

        self._ensure_clipboard()
        if not data:
            data = self._textinput.copy()
        return Clipboard.copy(data)

    def paste(self):
        ''' Insert text from system :class:`~kivy.core.clipboard.Clipboard`
        into the :class:`~kivy.uix.textinput.TextInput` at current cursor
        position.

        .. versionadded:: 1.8.0

        '''
        self._ensure_clipboard()
        data = Clipboard.paste()
        self._textinput.paste(data)

    def _update_cutbuffer(self, *args):
        CutBuffer.set_cutbuffer(self.selection_text)

    def _get_text_width(self, text, tab_width, _label_cached):
        """Return the width of a text, according to the current line options"""
        kw = self._get_line_options()

        try:
            cid = u'{}\0{}\0{}'.format(text, self.password, kw)
        except UnicodeDecodeError:
            cid = '{}\0{}\0{}'.format(text, self.password, kw)

        width = Cache_get('textinput.width', cid)
        if width:
            return width
        if not _label_cached:
            _label_cached = self._label_cached
        text = text.replace('\t', ' ' * tab_width)
        if not self.password:
            width = _label_cached.get_extents(text)[0]
        else:
            width = _label_cached.get_extents(
                self.password_mask * len(text))[0]
        Cache_append('textinput.width', cid, width)
        return width

    def on_cursor_blink(self, instance, value):
        """trigger blink event reset to switch blinking while focused"""
        self._reset_cursor_blink()

    def _do_blink_cursor(self, dt):
        if not self.cursor_blink:
            # ignore event if not triggered,
            # stop if cursor_blink value changed right now
            if self._do_blink_cursor_ev.is_triggered:
                self._do_blink_cursor_ev.cancel()
            # don't blink, make cursor visible
            self._cursor_blink = False
            return

        # Callback for blinking the cursor.
        self._cursor_blink = not self._cursor_blink

    def _reset_cursor_blink(self, *args):
        self._do_blink_cursor_ev.cancel()
        self._cursor_blink = False
        self._do_blink_cursor_ev()

    def on_cursor(self, instance, value):
        """
        When the cursor is moved, reset cursor blinking to keep it showing,
        and update all the graphics.
        """
        if self.focus:
            self._trigger_cursor_reset()
        self._trigger_update_graphics()

        # FIXME: this is not a good approach.
        self._textinput.select(self.cursor_index(), self.cursor_index())

    def _trigger_refresh_line_options(self, *largs):
        if self._refresh_line_options_ev is not None:
            self._refresh_line_options_ev.cancel()
        else:
            self._refresh_line_options_ev = Clock.create_trigger(
                self._refresh_line_options, 0)
        self._refresh_line_options_ev()

    def _refresh_line_options(self, *largs):
        self._line_options = None
        self._get_line_options()
        self._refresh_text_from_property()
        self._refresh_hint_text()
        self.cursor = self.get_cursor_from_index(len(self._current_text))

    def _trigger_refresh_text(self, *largs):
        if len(largs) and largs[0] == self:
            largs = ()
        if self._refresh_text_from_property_ev is not None:
            self._refresh_text_from_property_ev.cancel()
        self._refresh_text_from_property_ev = Clock.schedule_once(
            lambda dt: self._refresh_text_from_property(*largs))

    def _update_text_options(self, *largs):
        Cache_remove('textinput.width')
        self._trigger_refresh_text()

    def _refresh_text_from_property(self, *largs):
        self._refresh_text(self._current_text, requestor="property")

    def _refresh_text(self, text, requestor="property"):
        """
        If the requestor is textinput, we can apply an algorithm to update
        only the lines that changed, instead of all the lines.

        If the requestor is property, we can't do that, cause we likely need
        to update all the lines.

        Additionally, by using cache in internal functions, this method should
        be fast.
        """

        # Get the cursor index before the text change, as we may need to compute
        # the new cursor index after the text change.
        cursor_index_before = self.cursor_index()

        if requestor == "textinput":

            replace_from_line = 0
            start_text_index = 0
            flags = 0

            # When the requestor is textinput we try to be as fast as possible,
            # avoiding to compute the whole text again.

            # 1) Can we apply the split_smart optimization? (We need at least 2 lines, and
            # the text needs to start with the previous text.)
            if len(self._lines_indexes) > 1 and text.find(self._rendered_text) == 0:

                insertion_point = bisect_left(self._lines_indexes, len(self._rendered_text))

                if insertion_point > 1:
                    # We need at least 1 line before the current one to update.
                    last_untouched_line = insertion_point - 2
                    start_text_index = self._lines_indexes[last_untouched_line]
                    replace_from_line = last_untouched_line + 1
                    flags = self._lines_flags[replace_from_line]

                    if text[start_text_index] == "\n":
                        # We don't want to update the line that contains the
                        # longest_text_match, so we need to skip the "\n".
                        start_text_index += 1

            _lines, _lines_flags, _lines_indexes = self._split_smart(
                text[start_text_index:], flags=flags
            )

            _lines = self._lines[:replace_from_line] + _lines
            self._lines_indexes[replace_from_line:] = [
                start_text_index + ix for ix in _lines_indexes
            ]
            self._lines_flags[replace_from_line:] = _lines_flags


            # 2) We just need to get the lines that changed, and update them.
            # This is faster than updating all the lines, and also supports
            # what we won't be able to do with the split_smart optimization.
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                isjunk=None,
                a=self._lines[replace_from_line:],
                b=_lines[replace_from_line:],
            ).get_opcodes():
                # Since, for performance reasons, we skipped the lines that
                # were involved in split_smart optimization, we need to
                # adjust the indexes.
                i1 += replace_from_line
                i2 += replace_from_line
                j1 += replace_from_line
                j2 += replace_from_line

                if tag == "equal":
                    # Nothing to do, the lines are the same.
                    continue

                if tag == "delete":
                    # We need to remove the lines that are deleted.
                    _lines_chunk = []
                elif tag in {"insert", "replace"}:
                    # We need to insert the lines that are inserted or replaced.
                    _lines_chunk = _lines[j1:j2]

                self._lines[i1:i2] = _lines_chunk
                _lines_labels = [self._create_line_label(x) for x in _lines_chunk]
                self._lines_labels[i1:i2] = _lines_labels
                self._lines_rects[i1:i2] = [Rectangle(size=x.size) for x in _lines_labels]

        elif requestor == "property":
            # No need to know which lines changed, since everything need to be
            # updated. Even the _split_smart method is called without any cache.
            _lines, self._lines_flags, self._lines_indexes = self._split_smart(text)
            self._lines_labels[:] = [self._create_line_label(x) for x in _lines]
            self._lines_rects[:] = [Rectangle(size=x.size) for x in self._lines_labels]
            self._lines[:] = _lines

        min_line_ht = self._label_cached.get_extents('_')[1]
        # with markup texture can be of height `1`
        self.line_height = max(self._lines_labels[0].height, min_line_ht)
        # self.line_spacing = 2
        # now, if the text change, maybe the cursor is not at the same place as
        # before. so, try to set the cursor on the good place
        previous_cursor_row = self.cursor_row
        self.cursor = self.get_cursor_from_index(
            self.cursor_index() if cursor_index_before is None else cursor_index_before
        )

        # if we back to a new line, reset the scroll, otherwise, the effect is
        # ugly
        if self.cursor_row != previous_cursor_row:
            self.scroll_x = 0

        # with the new text don't forget to update graphics again
        self._trigger_update_graphics()

        self._rendered_text = text

    def _trigger_update_graphics(self, *largs):
        self._update_graphics_ev.cancel()
        self._update_graphics_ev()

    def _update_graphics(self, *largs):
        """
        Update all the graphics according to the current internal values.
        """

        # This is a little bit complex, because we have to :
        #     - handle scroll_x
        #     - handle padding
        #     - create rectangle for the lines matching the viewport
        #     - crop the texture coordinates to match the viewport

        # This is the first step of graphics, the second is the selection.

        self.canvas.clear()

        line_height = self.line_height
        dy = line_height + self.line_spacing

        # adjust view if the cursor is going outside the bounds
        scroll_x = self.scroll_x
        scroll_y = self.scroll_y

        # draw labels
        if (
            not self._lines
            or (not self._lines[0] and len(self._lines) == 1)
        ):
            rects = self._hint_text_rects
            labels = self._hint_text_labels
            lines = self._hint_text_lines
        else:
            rects = self._lines_rects
            labels = self._lines_labels
            lines = self._lines

        padding_left, padding_top, padding_right, padding_bottom = self.padding
        x = self.x + padding_left
        y = self.top - padding_top + scroll_y
        miny = self.y + padding_bottom
        maxy = self.top - padding_top
        halign = self.halign
        base_dir = self.base_direction

        auto_halign_r = halign == 'auto' and base_dir and 'rtl' in base_dir

        fst_visible_ln = None
        viewport_pos = scroll_x, 0
        for line_num, value in enumerate(lines):
            if miny < y < maxy + dy:
                if fst_visible_ln is None:
                    fst_visible_ln = line_num

                y = self._draw_line(
                    value,
                    line_num,
                    labels[line_num],
                    viewport_pos,
                    line_height,
                    miny,
                    maxy,
                    x,
                    y,
                    base_dir,
                    halign,
                    rects,
                    auto_halign_r,
                )
            elif y <= miny:
                line_num -= 1
                break

            y -= dy

        if fst_visible_ln is not None:
            self._visible_lines_range = (fst_visible_ln, line_num + 1)
        else:
            self._visible_lines_range = 0, 0

        self._update_graphics_selection()

    def _draw_line(
        self,
        value,
        line_num,
        texture,
        viewport_pos,
        line_height,
        miny,
        maxy,
        x,
        y,
        base_dir,
        halign,
        rects,
        auto_halign_r,
    ):
        size = list(texture.size)
        texcoords = texture.tex_coords[:]

        # compute coordinate
        padding_left, padding_top, padding_right, padding_bottom = self.padding
        viewport_width = self.width - padding_left - padding_right
        viewport_height = self.height - padding_top - padding_bottom
        texture_width, texture_height = size
        original_height, original_width = tch, tcw = texcoords[1:3]

        # adjust size/texcoord according to viewport
        if viewport_pos:
            tcx, tcy = viewport_pos
            tcx = tcx / texture_width * original_width
            tcy = tcy / texture_height * original_height

        else:
            tcx, tcy = 0, 0

        if texture_width * (1 - tcx) < viewport_width:
            tcw = tcw - tcx
            texture_width = tcw * texture_width
        elif viewport_width < texture_width:
            tcw = (viewport_width / texture_width) * tcw
            texture_width = viewport_width

        if viewport_height < texture_height:
            tch = (viewport_height / texture_height) * tch
            texture_height = viewport_height

        # cropping
        if y > maxy:
            viewport_height = (maxy - y + line_height)
            tch = (viewport_height / line_height) * original_height
            tcy = original_height - tch
            texture_height = viewport_height
        if y - line_height < miny:
            diff = miny - (y - line_height)
            y += diff
            viewport_height = line_height - diff
            tch = (viewport_height / line_height) * original_height
            texture_height = viewport_height

        if tcw < 0:
            # nothing to show
            return y

        top_left_corner = tcx, tcy + tch
        top_right_corner = tcx + tcw, tcy + tch
        bottom_right_corner = tcx + tcw, tcy
        bottom_left_corner = tcx, tcy

        texcoords = (
            top_left_corner
            + top_right_corner
            + bottom_right_corner
            + bottom_left_corner
        )

        # Horizontal alignment
        xoffset = 0
        if not base_dir:
            base_dir = self._resolved_base_dir = Label.find_base_direction(value)  # noqa
            if base_dir and halign == 'auto':
                auto_halign_r = 'rtl' in base_dir
        if halign == 'center':
            xoffset = int((viewport_width - texture_width) / 2.)
        elif halign == 'right' or auto_halign_r:
            xoffset = max(0, int(viewport_width - texture_width))

        # add rectangle
        rect = rects[line_num]
        rect.pos = int(xoffset + x), int(y - line_height)
        rect.size = texture_width, texture_height
        rect.texture = texture
        rect.tex_coords = texcoords
        # useful to debug rectangle sizes
        # self.canvas.add(Color(0, .5, 0, .5, mode='rgba'))
        # self.canvas.add(Rectangle(pos=rect.pos, size=rect.size))
        # self.canvas.add(Color())
        self.canvas.add(rect)

        return y

    def _update_graphics_selection(self):
        if not self._selection:
            return

        # local references to avoid dot lookups later
        padding_left, padding_top, padding_right, padding_bottom = self.padding
        rects = self._lines_rects
        label_cached = self._label_cached
        lines = self._lines
        tab_width = self.tab_width
        top = self.top
        get_text_width = self._get_text_width
        get_cursor_from_index = self.get_cursor_from_index
        draw_selection = self._draw_selection
        canvas_add = self.canvas.add
        selection_color = self.selection_color

        # selection borders
        a, b = sorted((self._selection_from, self._selection_to))
        selection_start_col, selection_start_row = get_cursor_from_index(a)
        selection_end_col, selection_end_row = get_cursor_from_index(b)

        dy = self.line_height + self.line_spacing
        x = self.x
        y = top - padding_top + self.scroll_y - selection_start_row * dy
        width = self.width

        miny = self.y + padding_bottom
        maxy = top - padding_top + dy

        self.canvas.remove_group('selection')
        first_visible_line = math.floor(self.scroll_y / dy)
        last_visible_line = math.ceil((self.scroll_y + maxy - miny) / dy)
        width_minus_padding = width - (padding_right + padding_left)

        for line_num, rect in enumerate(
            islice(
                rects,
                max(selection_start_row, first_visible_line),
                min(selection_end_row + 1, last_visible_line - 1),
            ),
            start=max(selection_start_row, first_visible_line)
        ):
            draw_selection(
                rect.pos,
                rect.size,
                line_num,
                (selection_start_col, selection_start_row),
                (selection_end_col, selection_end_row),
                lines,
                get_text_width,
                tab_width,
                label_cached,
                width_minus_padding,
                padding_left,
                padding_right,
                x,
                canvas_add,
                selection_color
            )
        self._position_handles('both')

    def _draw_selection(
        self,
        pos,
        size,
        line_num,
        selection_start,
        selection_end,
        lines,
        get_text_width,
        tab_width,
        label_cached,
        width_minus_padding,
        padding_left,
        padding_right,
        x,
        canvas_add,
        selection_color
    ):
        selection_start_col, selection_start_row = selection_start
        selection_end_col, selection_end_row = selection_end

        # Draw the current selection on the widget.
        if not selection_start_row <= line_num <= selection_end_row:
            return
        x, y = pos
        w, h = size
        beg = x
        end = x + w

        if line_num == selection_start_row:
            line = lines[line_num]
            beg -= self.scroll_x
            beg += get_text_width(
                line[:selection_start_col],
                tab_width,
                label_cached
            )

        if line_num == selection_end_row:
            line = lines[line_num]
            end = (x - self.scroll_x) + get_text_width(
                line[:selection_end_col],
                tab_width,
                label_cached
            )

        beg = boundary(beg, x, x + width_minus_padding)
        end = boundary(end, x, x + width_minus_padding)
        if beg == end:
            return

        canvas_add(Color(*selection_color, group='selection'))
        canvas_add(
            Rectangle(
                pos=(beg, y),
                size=(end - beg, h),
                group='selection'
            )
        )

    def on_size(self, instance, value):
        # if the size change, we might do invalid scrolling / text split
        # size the text maybe be put after size_hint have been resolved.
        self._trigger_refresh_text()
        self._refresh_hint_text()
        self.scroll_x = self.scroll_y = 0

    def _get_row_width(self, row):
        # Get the pixel width of the given row.
        _labels = self._lines_labels
        if row < len(_labels):
            return _labels[row].width
        return 0

    def _get_cursor_pos(self):
        # return the current cursor x/y from the row/col
        dy = self.line_height + self.line_spacing
        padding_left = self.padding[0]
        padding_top = self.padding[1]
        padding_right = self.padding[2]
        left = self.x + padding_left
        top = self.top - padding_top
        y = top + self.scroll_y
        y -= self.cursor_row * dy

        # Horizontal alignment
        halign = self.halign
        viewport_width = self.width - padding_left - padding_right
        cursor_offset = self.cursor_offset()
        base_dir = self.base_direction or self._resolved_base_dir
        auto_halign_r = halign == 'auto' and base_dir and 'rtl' in base_dir
        if halign == 'center':
            row_width = self._get_row_width(self.cursor_row)
            x = (
                left
                + max(0, (viewport_width - row_width) // 2)
                + cursor_offset
                - self.scroll_x
            )
        elif halign == 'right' or auto_halign_r:
            row_width = self._get_row_width(self.cursor_row)
            x = (
                left
                + max(0, viewport_width - row_width)
                + cursor_offset
                - self.scroll_x
            )
        else:
            x = left + cursor_offset - self.scroll_x

        return x, y

    def _get_cursor_visual_height(self):
        # Return the height of the cursor's visible part
        _, cy = map(int, self.cursor_pos)
        max_y = self.top - self.padding[1]
        min_y = self.y + self.padding[3]

        lh = self.line_height
        if cy > max_y:
            return lh - min(lh, cy - max_y)
        else:
            return min(lh, max(0, cy - min_y))

    def _get_cursor_visual_pos(self):
        # Return the position of the cursor's top visible point
        cx, cy = map(int, self.cursor_pos)
        max_y = self.top - self.padding[3]
        return [cx, min(max_y, cy)]

    def _get_line_options(self):
        # Get or create line options, to be used for Label creation
        if self._line_options is None:
            self._line_options = kw = {
                'font_size': self.font_size,
                'font_name': self.font_name,
                'font_context': self.font_context,
                'font_family': self.font_family,
                'text_language': self.text_language,
                'base_direction': self.base_direction,
                'anchor_x': 'left',
                'anchor_y': 'top',
                'padding_x': 0,
                'padding_y': 0,
                'padding': (0, 0)
            }
            self._label_cached = Label(**kw)
        return self._line_options

    def _create_line_label(self, text, hint=False):
        """
        Create a label from a text, using line options, and cache the result.
        If the text is the same, the same label will be returned from cache. 
        """
        ntext = text.replace('\n', '').replace('\t', ' ' * self.tab_width)

        if self.password and not hint:  # Don't replace hint_text with *
            ntext = self.password_mask * len(ntext)

        kw = self._get_line_options()
        cid = '%s\0%s' % (ntext, str(kw))
        texture = Cache_get('textinput.label', cid)

        if texture is None:
            # FIXME right now, we can't render very long line...
            # if we move on "VBO" version as fallback, we won't need to
            # do this. try to find the maximum text we can handle
            label = None
            label_len = len(ntext)
            ld = None

            # check for blank line
            if not ntext:
                texture = Texture.create(size=(1, 1))
                Cache_append('textinput.label', cid, texture)
                return texture

            while True:
                try:
                    label = Label(text=ntext[:label_len], **kw)
                    label.refresh()
                    if ld is not None and ld > 2:
                        ld //= 2
                        label_len += ld
                    else:
                        break

                except:
                    # exception happen when we tried to render the text
                    # reduce it...
                    if ld is None:
                        ld = len(ntext)
                    ld //= 2
                    if ld < 2 and label_len:
                        label_len -= 1
                    label_len -= ld
                    continue

            # ok, we found it.
            texture = label.texture
            Cache_append('textinput.label', cid, texture)
        return texture

    _tokenize_delimiters = u' .,:;!?\r\t'

    def _tokenize(self, text):
        # Tokenize a text string from some delimiters
        if text is None:
            return
        delimiters = self._tokenize_delimiters
        old_index = 0
        prev_char = ''
        for index, char in enumerate(text):
            if char not in delimiters:
                if char != u'\n':
                    if index > 0 and (prev_char in delimiters):
                        if old_index < index:
                            yield text[old_index:index], index
                        old_index = index
                else:
                    if old_index < index:
                        yield text[old_index:index], index
                    yield text[index:index + 1], index
                    old_index = index + 1
            prev_char = char
        yield text[old_index:], len(text)

    def _split_smart(self, text, flags=0):
        """
        Do a "smart" split. If not multiline, or if wrap is set,
        we are not doing smart split, just a split on line break.
        Otherwise, we are trying to split as soon as possible, to prevent
        overflow on the widget.
        """

        # depend of the options, split the text on line, or word
        if not self.multiline or not self.do_wrap:
            lines = text.split(u'\n')
            lines_flags = [0] + [FL_IS_LINEBREAK] * (len(lines) - 1)
            return lines, lines_flags, []

        # no autosize, do wordwrap.
        x = 0
        flags = flags
        line = []
        line_index = 0
        lines = []
        lines_flags = []
        lines_text_indexes = []
        _join = ''.join
        padding_left = self.padding[0]
        padding_right = self.padding[2]
        width = self.width - padding_left - padding_right
        _tab_width, _label_cached = self.tab_width, self._label_cached

        # try to add each word on current line.
        words_widths = {}
        for word, word_end_index in self._tokenize(text):
            is_newline = (word == u'\n')
            try:
                w = words_widths[word]
            except KeyError:
                w = self._get_text_width(word, _tab_width, _label_cached)
                words_widths[word] = w
            # if we have more than the width, or if it's a newline,
            # push the current line, and create a new one
            if (x + w > width and line) or is_newline:
                lines.append(_join(line))
                lines_flags.append(flags)
                lines_text_indexes.append(line_index)
                flags = 0
                line = []
                x = 0
            if is_newline:
                flags |= FL_IS_LINEBREAK
            elif width >= 1 and w > width:
                while w > width:
                    split_width = split_pos = 0
                    # split the word
                    for c in word:
                        try:
                            cw = words_widths[c]
                        except KeyError:
                            cw = self._get_text_width(c, _tab_width, _label_cached)
                            words_widths[c] = cw
                        if split_width + cw > width:
                            break
                        split_width += cw
                        split_pos += 1
                    if split_width == split_pos == 0:
                        # can't fit the word in, give up
                        break
                    line_index = word_end_index - split_pos
                    lines.append(word[:split_pos])
                    lines_flags.append(flags)
                    lines_text_indexes.append(line_index)
                    flags = FL_IS_WORDBREAK
                    word = word[split_pos:]
                    w -= split_width
                x = w
                line.append(word)
                line_index = word_end_index
            else:
                x += w
                line.append(word)
                line_index = word_end_index
        if line or flags & FL_IS_LINEBREAK:
            lines.append(_join(line))
            lines_flags.append(flags)
            lines_text_indexes.append(line_index)

        return lines, lines_flags, lines_text_indexes

    def _handle_coretextinput_shortcut(self, instance, key):
        # actions that can be done in readonly
        if key == ord('a'):  # select all
            self.select_all()
        elif key == ord('c'):  # copy selection
            self.copy()

        if not self._editable:
            return

        # actions that can be done only if editable
        if key == ord('x'):  # cut selection
            self.cut()
        elif key == ord('v'):  # paste clipboard content
            self.paste()
        elif key == ord('z'):  # undo
            self.do_undo()
        elif key == ord('r'):  # redo
            self.do_redo()

    def _handle_coretextinput_focus(self, instance, value):
        # The core textinput has gained or lost focus, so we need to update
        # our focus property accordingly.
        self.focus = value

    def _handle_coretextinput_action(self, instance, action):
        # Handle any FocusBehavior action before TextInput's
        # (e.g: tab, escape)
        if action == "escape":
            self.focus = False

        if action == "tab":
            self.move_focus(direction="next")

        if action == "shifttab":
            self.move_focus(direction="previous")

        if action == "enter":
            self.dispatch("on_text_validate")
            if self.text_validate_unfocus:
                self.focus = False

        if action == "shift":
            Logger.debug("TextInput: shift pressed")

        if action.startswith("cursor_"):
            self.do_cursor_movement(action)

    def on__hint_text(self, instance, value):
        self._refresh_hint_text()

    def _refresh_hint_text(self):
        _lines, self._hint_text_flags, _lines_indexes = self._split_smart(self.hint_text)
        _hint_text_labels = []
        _hint_text_rects = []

        for x in _lines:
            lbl = self._create_line_label(x, hint=True)
            _hint_text_labels.append(lbl)
            _hint_text_rects.append(Rectangle(size=lbl.size))

        self._hint_text_lines[:] = _lines
        self._hint_text_labels = _hint_text_labels
        self._hint_text_rects = _hint_text_rects

        # Remember to update graphics
        self._trigger_update_graphics()

    #
    # Properties
    #

    _lines = ListProperty([])
    _hint_text_lines = ListProperty([])
    _editable = BooleanProperty(True)
    _insert_int_pat = re.compile(u'^-?[0-9]*$')
    _insert_float_pat = re.compile(u'^-?[0-9]*\\.?[0-9]*$')
    _cursor_blink = BooleanProperty(False)
    _cursor_visual_pos = AliasProperty(
        _get_cursor_visual_pos, None, bind=['cursor_pos']
    )
    _cursor_visual_height = AliasProperty(
        _get_cursor_visual_height, None, bind=['cursor_pos']
    )

    readonly = BooleanProperty(False)
    '''If True, the user will not be able to change the content of a textinput.

    .. versionadded:: 1.3.0

    :attr:`readonly` is a :class:`~kivy.properties.BooleanProperty` and
    defaults to False.
    '''

    text_validate_unfocus = BooleanProperty(True)
    '''If True, the :meth:`TextInput.on_text_validate` event will unfocus the
    widget, therefore make it stop listening to the keyboard. When disabled,
    the :meth:`TextInput.on_text_validate` event can be fired multiple times
    as the result of TextInput keeping the focus enabled.

    .. versionadded:: 1.10.1

    :attr:`text_validate_unfocus` is
    a :class:`~kivy.properties.BooleanProperty` and defaults to True.
    '''

    multiline = BooleanProperty(True)
    '''If True, the widget will be able show multiple lines of text. If False,
    the "enter" keypress will defocus the textinput instead of adding a new
    line.

    :attr:`multiline` is a :class:`~kivy.properties.BooleanProperty` and
    defaults to True.
    '''

    do_wrap = BooleanProperty(True)
    '''If True, and the text is multiline, then lines larger than the width of
    the widget will wrap around to the next line, avoiding the need for
    horizontal scrolling. Disabling this option ensure one line is always
    displayed as one line.

    :attr:`do_wrap` is a :class:`~kivy.properties.BooleanProperty` and defaults
    to True.

    versionadded:: 2.1.0
    '''

    password = BooleanProperty(False)
    '''If True, the widget will display its characters as the character
    set in :attr:`password_mask`.

    .. versionadded:: 1.2.0

    :attr:`password` is a :class:`~kivy.properties.BooleanProperty` and
    defaults to False.
    '''

    password_mask = StringProperty('*')
    '''Sets the character used to mask the text when :attr:`password` is True.

    .. versionadded:: 1.10.0

    :attr:`password_mask` is a :class:`~kivy.properties.StringProperty` and
    defaults to `'*'`.
    '''

    cursor_blink = BooleanProperty(True)
    '''This property is used to set whether the graphic cursor should blink
    or not.

    .. versionchanged:: 1.10.1
        `cursor_blink` has been refactored to enable switching the blinking
        on/off and the previous behavior has been moved to a private
        `_cursor_blink` property. The previous default value `False` has been
        changed to `True`.

    :attr:`cursor_blink` is a :class:`~kivy.properties.BooleanProperty` and
    defaults to True.
    '''

    def _get_cursor(self):
        return self._cursor

    def _set_cursor(self, pos):
        if not self._lines:
            self._trigger_refresh_text()
            return
        l = self._lines
        cr = boundary(pos[1], 0, len(l) - 1)
        cc = boundary(pos[0], 0, len(l[cr]))
        cursor = cc, cr

        # adjust scrollview to ensure that the cursor will be always inside our
        # viewport.
        self._adjust_viewport(cc, cr)

        if self._cursor == cursor:
            return

        self._cursor = cursor
        return True

    @triggered(timeout=-1)
    def _adjust_viewport(self, cc, cr):
        padding_left = self.padding[0]
        padding_right = self.padding[2]
        viewport_width = self.width - padding_left - padding_right
        sx = self.scroll_x
        base_dir = self.base_direction or self._resolved_base_dir
        auto_halign_r = (
            self.halign == 'auto'
            and base_dir
            and 'rtl' in base_dir
        )

        offset = self.cursor_offset()
        row_width = self._get_row_width(self.cursor_row)

        # if offset is outside the current bounds, readjust
        if offset - sx >= viewport_width:
            self.scroll_x = offset - viewport_width
        elif offset < sx + 1:
            self.scroll_x = offset

        # Avoid right/center horizontal alignment issues if the viewport is at
        # the end of the line, if not multiline.
        viewport_scroll_x = row_width - viewport_width
        if (
            not self.multiline
            and offset >= viewport_scroll_x
            and self.scroll_x >= viewport_scroll_x
            and (
                self.halign == "center"
                or self.halign == "right"
                or auto_halign_r
            )
        ):
            self.scroll_x = max(0, viewport_scroll_x)

        # do the same for Y
        # this algo try to center the cursor as much as possible
        dy = self.line_height + self.line_spacing
        offsety = cr * dy

        padding_top = self.padding[1]
        padding_bottom = self.padding[3]
        viewport_height = self.height - padding_top - padding_bottom - dy

        sy = self.scroll_y
        if offsety > viewport_height + sy:
            self.scroll_y = offsety - viewport_height
        elif offsety < sy:
            self.scroll_y = offsety

    cursor = AliasProperty(_get_cursor, _set_cursor)
    '''Tuple of (col, row) values indicating the current cursor position.
    You can set a new (col, row) if you want to move the cursor. The scrolling
    area will be automatically updated to ensure that the cursor is
    visible inside the viewport.

    :attr:`cursor` is an :class:`~kivy.properties.AliasProperty`.
    '''

    def _get_cursor_col(self):
        return self._cursor[0]

    cursor_col = AliasProperty(_get_cursor_col, None, bind=('cursor', ))
    '''Current column of the cursor.

    :attr:`cursor_col` is an :class:`~kivy.properties.AliasProperty` to
    cursor[0], read-only.
    '''

    def _get_cursor_row(self):
        return self._cursor[1]

    cursor_row = AliasProperty(_get_cursor_row, None, bind=('cursor', ))
    '''Current row of the cursor.

    :attr:`cursor_row` is an :class:`~kivy.properties.AliasProperty` to
    cursor[1], read-only.
    '''

    cursor_pos = AliasProperty(_get_cursor_pos, None,
                               bind=('cursor', 'padding', 'pos', 'size',
                                     'focus', 'scroll_x', 'scroll_y',
                                     'line_height', 'line_spacing'),
                               cache=False)
    '''Current position of the cursor, in (x, y).

    :attr:`cursor_pos` is an :class:`~kivy.properties.AliasProperty`,
    read-only.
    '''

    cursor_color = ColorProperty([1, 0, 0, 1])
    '''Current color of the cursor, in (r, g, b, a) format.

    .. versionadded:: 1.9.0

    :attr:`cursor_color` is a :class:`~kivy.properties.ColorProperty` and
    defaults to [1, 0, 0, 1].

    .. versionchanged:: 2.0.0
        Changed from :class:`~kivy.properties.ListProperty` to
        :class:`~kivy.properties.ColorProperty`.
    '''

    cursor_width = NumericProperty('1sp')
    '''Current width of the cursor.

    .. versionadded:: 1.10.0

    :attr:`cursor_width` is a :class:`~kivy.properties.NumericProperty` and
    defaults to '1sp'.
    '''

    line_height = NumericProperty(1)
    '''Height of a line. This property is automatically computed from the
    :attr:`font_name`, :attr:`font_size`. Changing the line_height will have
    no impact.

    .. note::

        :attr:`line_height` is the height of a single line of text.
        Use :attr:`minimum_height`, which also includes padding, to
        get the height required to display the text properly.

    :attr:`line_height` is a :class:`~kivy.properties.NumericProperty`,
    read-only.
    '''

    tab_width = NumericProperty(4)
    '''By default, each tab will be replaced by four spaces on the text
    input widget. You can set a lower or higher value.

    :attr:`tab_width` is a :class:`~kivy.properties.NumericProperty` and
    defaults to 4.
    '''

    padding_x = VariableListProperty([0, 0], length=2, deprecated=True)
    '''Horizontal padding of the text: [padding_left, padding_right].

    padding_x also accepts a one argument form [padding_horizontal].

    :attr:`padding_x` is a :class:`~kivy.properties.VariableListProperty` and
    defaults to [0, 0]. This might be changed by the current theme.

    .. deprecated:: 1.7.0
        Use :attr:`padding` instead.
    '''

    def on_padding_x(self, instance, value):
        self.padding[0] = value[0]
        self.padding[2] = value[1]

    padding_y = VariableListProperty([0, 0], length=2, deprecated=True)
    '''Vertical padding of the text: [padding_top, padding_bottom].

    padding_y also accepts a one argument form [padding_vertical].

    :attr:`padding_y` is a :class:`~kivy.properties.VariableListProperty` and
    defaults to [0, 0]. This might be changed by the current theme.

    .. deprecated:: 1.7.0
        Use :attr:`padding` instead.
    '''

    def on_padding_y(self, instance, value):
        self.padding[1] = value[0]
        self.padding[3] = value[1]

    padding = VariableListProperty([6, 6, 6, 6])
    '''Padding of the text: [padding_left, padding_top, padding_right,
    padding_bottom].

    padding also accepts a two argument form [padding_horizontal,
    padding_vertical] and a one argument form [padding].

    .. versionchanged:: 1.7.0
        Replaced AliasProperty with VariableListProperty.

    :attr:`padding` is a :class:`~kivy.properties.VariableListProperty` and
    defaults to [6, 6, 6, 6].
    '''

    halign = OptionProperty('auto', options=['left', 'center', 'right',
                            'auto'])
    '''Horizontal alignment of the text.

    :attr:`halign` is an :class:`~kivy.properties.OptionProperty` and
    defaults to 'auto'. Available options are : auto, left, center and right.
    Auto will attempt to autodetect horizontal alignment for RTL text (Pango
    only), otherwise it behaves like `left`.

    .. versionadded:: 1.10.1
    '''

    scroll_x = NumericProperty(0)
    '''X scrolling value of the viewport. The scrolling is automatically
    updated when the cursor is moved or text changed. If there is no
    user input, the scroll_x and scroll_y properties may be changed.

    :attr:`scroll_x` is a :class:`~kivy.properties.NumericProperty` and
    defaults to 0.
    '''

    scroll_y = NumericProperty(0)
    '''Y scrolling value of the viewport. See :attr:`scroll_x` for more
    information.

    :attr:`scroll_y` is a :class:`~kivy.properties.NumericProperty` and
    defaults to 0.
    '''

    selection_color = ColorProperty([0.1843, 0.6549, 0.8313, .5])
    '''Current color of the selection, in (r, g, b, a) format.

    .. warning::

        The color should always have an "alpha" component less than 1
        since the selection is drawn after the text.

    :attr:`selection_color` is a :class:`~kivy.properties.ColorProperty` and
    defaults to [0.1843, 0.6549, 0.8313, .5].

    .. versionchanged:: 2.0.0
        Changed from :class:`~kivy.properties.ListProperty` to
        :class:`~kivy.properties.ColorProperty`.
    '''

    border = ListProperty([4, 4, 4, 4])
    '''Border used for :class:`~kivy.graphics.vertex_instructions.BorderImage`
    graphics instruction. Used with :attr:`background_normal` and
    :attr:`background_active`. Can be used for a custom background.

    .. versionadded:: 1.4.1

    It must be a list of four values: (bottom, right, top, left). Read the
    BorderImage instruction for more information about how to use it.

    :attr:`border` is a :class:`~kivy.properties.ListProperty` and defaults
    to (4, 4, 4, 4).
    '''

    background_normal = StringProperty(
        'atlas://data/images/defaulttheme/textinput')
    '''Background image of the TextInput when it's not in focus.

    .. versionadded:: 1.4.1

    :attr:`background_normal` is a :class:`~kivy.properties.StringProperty` and
    defaults to 'atlas://data/images/defaulttheme/textinput'.
    '''

    background_disabled_normal = StringProperty(
        'atlas://data/images/defaulttheme/textinput_disabled')
    '''Background image of the TextInput when disabled.

    .. versionadded:: 1.8.0

    :attr:`background_disabled_normal` is a
    :class:`~kivy.properties.StringProperty` and
    defaults to 'atlas://data/images/defaulttheme/textinput_disabled'.
    '''

    background_active = StringProperty(
        'atlas://data/images/defaulttheme/textinput_active')
    '''Background image of the TextInput when it's in focus.

    .. versionadded:: 1.4.1

    :attr:`background_active` is a
    :class:`~kivy.properties.StringProperty` and
    defaults to 'atlas://data/images/defaulttheme/textinput_active'.
    '''

    background_color = ColorProperty([1, 1, 1, 1])
    '''Current color of the background, in (r, g, b, a) format.

    .. versionadded:: 1.2.0

    :attr:`background_color` is a :class:`~kivy.properties.ColorProperty`
    and defaults to [1, 1, 1, 1] (white).

    .. versionchanged:: 2.0.0
        Changed from :class:`~kivy.properties.ListProperty` to
        :class:`~kivy.properties.ColorProperty`.
    '''

    foreground_color = ColorProperty([0, 0, 0, 1])
    '''Current color of the foreground, in (r, g, b, a) format.

    .. versionadded:: 1.2.0

    :attr:`foreground_color` is a :class:`~kivy.properties.ColorProperty`
    and defaults to [0, 0, 0, 1] (black).

    .. versionchanged:: 2.0.0
        Changed from :class:`~kivy.properties.ListProperty` to
        :class:`~kivy.properties.ColorProperty`.
    '''

    disabled_foreground_color = ColorProperty([0, 0, 0, .5])
    '''Current color of the foreground when disabled, in (r, g, b, a) format.

    .. versionadded:: 1.8.0

    :attr:`disabled_foreground_color` is a
    :class:`~kivy.properties.ColorProperty` and
    defaults to [0, 0, 0, 5] (50% transparent black).

    .. versionchanged:: 2.0.0
        Changed from :class:`~kivy.properties.ListProperty` to
        :class:`~kivy.properties.ColorProperty`.
    '''

    use_bubble = BooleanProperty(not _is_desktop)
    '''Indicates whether the cut/copy/paste bubble is used.

    .. versionadded:: 1.7.0

    :attr:`use_bubble` is a :class:`~kivy.properties.BooleanProperty`
    and defaults to True on mobile OS's, False on desktop OS's.
    '''

    use_handles = BooleanProperty(not _is_desktop)
    '''Indicates whether the selection handles are displayed.

    .. versionadded:: 1.8.0

    :attr:`use_handles` is a :class:`~kivy.properties.BooleanProperty`
    and defaults to True on mobile OS's, False on desktop OS's.
    '''

    scroll_from_swipe = BooleanProperty(not _is_desktop)
    '''Allow to scroll the text using swipe gesture according to
    :attr:`scroll_timeout` and :attr:`scroll_distance`.

    .. versionadded:: 2.1.0

    :attr:`scroll_from_swipe` is a BooleanProperty and defaults to True on
    mobile OS’s, False on desktop OS’s.
    '''

    scroll_distance = NumericProperty(_scroll_distance)
    '''Minimum distance to move before change from scroll to selection mode, in
    pixels.
    It is advisable that you base this value on the dpi of your target device's
    screen.

    .. versionadded:: 2.1.0

    :attr:`scroll_distance` is a NumericProperty and defaults to  20 pixels.
    '''

    scroll_timeout = NumericProperty(_scroll_timeout)
    '''Timeout allowed to trigger the :attr:`scroll_distance`, in milliseconds.
    If the user has not moved :attr:`scroll_distance` within the timeout, the
    scrolling will be disabled, and the selection mode will start.

    .. versionadded:: 2.1.0

    :attr:`scroll_timeout` is a NumericProperty and defaults to 250
    milliseconds.
    '''

    def get_sel_from(self):
        return self._selection_from

    selection_from = AliasProperty(get_sel_from, None)
    '''If a selection is in progress or complete, this property will represent
    the cursor index where the selection started.

    .. versionchanged:: 1.4.0
        :attr:`selection_from` is an :class:`~kivy.properties.AliasProperty`
        and defaults to None, readonly.
    '''

    def get_sel_to(self):
        return self._selection_to

    selection_to = AliasProperty(get_sel_to, None)
    '''If a selection is in progress or complete, this property will represent
    the cursor index where the selection started.

    .. versionchanged:: 1.4.0
        :attr:`selection_to` is an :class:`~kivy.properties.AliasProperty` and
        defaults to None, readonly.
    '''

    def _get_selected_text(self):
        return self._textinput.selected_text

    selection_text = AliasProperty(_get_selected_text, None)
    '''Current content selection.

    :attr:`selection_text` is a :class:`~kivy.properties.StringProperty`
    and defaults to '', readonly.
    '''

    def on_selection_text(self, instance, value):
        # FIXME: Why CutBuffer?
        if value:
            if self.use_handles:
                self._trigger_show_handles()
            if CutBuffer and not self.password:
                self._trigger_update_cutbuffer()

    def _get_text(self):
        return self._current_text

    def _set_text(self, text):
        if isinstance(text, bytes):
            text = text.decode('utf8')
        if self._textinput.text != text:
            self._textinput.text = text

    _current_text = StringProperty("")

    text = AliasProperty(_get_text, _set_text, bind=('_current_text',))
    '''Text of the widget.

    Creation of a simple hello world::

        widget = TextInput(text='Hello world')

    If you want to create the widget with an unicode string, use::

        widget = TextInput(text=u'My unicode string')

    :attr:`text` is an :class:`~kivy.properties.AliasProperty`.
    '''

    font_name = StringProperty(DEFAULT_FONT)
    '''Filename of the font to use. The path can be absolute or relative.
    Relative paths are resolved by the :func:`~kivy.resources.resource_find`
    function.

    .. warning::

        Depending on your text provider, the font file may be ignored. However,
        you can mostly use this without problems.

        If the font used lacks the glyphs for the particular language/symbols
        you are using, you will see '[]' blank box characters instead of the
        actual glyphs. The solution is to use a font that has the glyphs you
        need to display. For example, to display |unicodechar|, use a font like
        freesans.ttf that has the glyph.

        .. |unicodechar| image:: images/unicode-char.png

    :attr:`font_name` is a :class:`~kivy.properties.StringProperty` and
    defaults to 'Roboto'. This value is taken
    from :class:`~kivy.config.Config`.
    '''

    font_size = NumericProperty('15sp')
    '''Font size of the text in pixels.

    :attr:`font_size` is a :class:`~kivy.properties.NumericProperty` and
    defaults to 15 :attr:`~kivy.metrics.sp`.
    '''

    font_context = StringProperty(None, allownone=True)
    '''Font context. `None` means the font is used in isolation, so you are
    guaranteed to be drawing with the TTF file resolved by :attr:`font_name`.
    Specifying a value here will load the font file into a named context,
    enabling fallback between all fonts in the same context. If a font
    context is set, you are not guaranteed that rendering will actually use
    the specified TTF file for all glyphs (Pango will pick the one it
    thinks is best).

    If Kivy is linked against a system-wide installation of FontConfig,
    you can load the system fonts by specifying a font context starting
    with the special string `system://`. This will load the system
    fontconfig configuration, and add your application-specific fonts on
    top of it (this imposes a significant risk of family name collision,
    Pango may not use your custom font file, but pick one from the system)

    .. note::
        This feature requires the Pango text provider.

    .. versionadded:: 1.10.1

    :attr:`font_context` is a :class:`~kivy.properties.StringProperty` and
    defaults to None.
    '''

    font_family = StringProperty(None, allownone=True)
    '''Font family, this is only applicable when using :attr:`font_context`
    option. The specified font family will be requested, but note that it may
    not be available, or there could be multiple fonts registered with the
    same family. The value can be a family name (string) available in the
    font context (for example a system font in a `system://` context, or a
    custom font file added using :class:`kivy.core.text.FontContextManager`).
    If set to `None`, font selection is controlled by the :attr:`font_name`
    setting.

    .. note::
        If using :attr:`font_name` to reference a custom font file, you
        should leave this as `None`. The family name is managed automatically
        in this case.

    .. note::
        This feature requires the Pango text provider.

    .. versionadded:: 1.10.1

    :attr:`font_family` is a :class:`~kivy.properties.StringProperty` and
    defaults to None.
    '''

    base_direction = OptionProperty(
        None,
        options=['ltr', 'rtl', 'weak_rtl', 'weak_ltr', None],
        allownone=True
    )
    '''Base direction of text, this impacts horizontal alignment when
    :attr:`halign` is `auto` (the default). Available options are: None,
    "ltr" (left to right), "rtl" (right to left) plus "weak_ltr" and
    "weak_rtl".

    .. note::
        This feature requires the Pango text provider.

    .. note::
        Weak modes are currently not implemented in Kivy text layout, and
        have the same effect as setting strong mode.

    .. versionadded:: 1.10.1

    :attr:`base_direction` is an :class:`~kivy.properties.OptionProperty` and
    defaults to None (autodetect RTL if possible, otherwise LTR).
    '''

    text_language = StringProperty(None, allownone=True)
    '''Language of the text, if None Pango will determine it from locale.
    This is an RFC-3066 format language tag (as a string), for example
    "en_US", "zh_CN", "fr" or "ja". This can impact font selection, metrics
    and rendering. For example, the same bytes of text can look different
    for `ur` and `ar` languages, though both use Arabic script.

    .. note::
        This feature requires the Pango text provider.

    .. versionadded:: 1.10.1

    :attr:`text_language` is a :class:`~kivy.properties.StringProperty` and
    defaults to None.
    '''

    _hint_text = StringProperty('')

    def _set_hint_text(self, value):
        if isinstance(value, bytes):
            value = value.decode('utf8')
        self._hint_text = value

    def _get_hint_text(self):
        return self._hint_text

    hint_text = AliasProperty(
        _get_hint_text, _set_hint_text, bind=('_hint_text', ))
    '''Hint text of the widget, shown if text is ''.

    .. versionadded:: 1.6.0

    .. versionchanged:: 1.10.0
        The property is now an AliasProperty and byte values are decoded to
        strings. The hint text will stay visible when the widget is focused.

    :attr:`hint_text` a :class:`~kivy.properties.AliasProperty` and defaults
    to ''.
    '''

    hint_text_color = ColorProperty([0.5, 0.5, 0.5, 1.0])
    '''Current color of the hint_text text, in (r, g, b, a) format.

    .. versionadded:: 1.6.0

    :attr:`hint_text_color` is a :class:`~kivy.properties.ColorProperty` and
    defaults to [0.5, 0.5, 0.5, 1.0] (grey).

    .. versionchanged:: 2.0.0
        Changed from :class:`~kivy.properties.ListProperty` to
        :class:`~kivy.properties.ColorProperty`.
    '''

    auto_indent = BooleanProperty(False)
    # TODO: Check the usage. We likely need to implement this in the TextInput
    # provider.
    '''Automatically indent multiline text.

    .. versionadded:: 1.7.0

    :attr:`auto_indent` is a :class:`~kivy.properties.BooleanProperty` and
    defaults to False.
    '''

    replace_crlf = BooleanProperty(True)
    # TODO: This property should be set to the TextInput provider, as it is
    # our source of truth for the text.
    '''Automatically replace CRLF with LF.

    .. versionadded:: 1.9.1

    :attr:`replace_crlf` is a :class:`~kivy.properties.BooleanProperty` and
    defaults to True.
    '''

    allow_copy = BooleanProperty(True)
    # TODO: Decide where to implement that. (TextInput provider?)
    '''Decides whether to allow copying the text.

    .. versionadded:: 1.8.0

    :attr:`allow_copy` is a :class:`~kivy.properties.BooleanProperty` and
    defaults to True.
    '''

    def _get_min_height(self):
        return (
            len(self._lines) * (self.line_height + self.line_spacing)
            + self.padding[1]
            + self.padding[3]
        )

    minimum_height = AliasProperty(
        _get_min_height,
        bind=(
            '_lines', 'line_spacing', 'padding', 'font_size', 'font_name',
            'password', 'font_context', 'hint_text', 'line_height'
        ),
        cache=True
    )
    '''Minimum height of the content inside the TextInput.

    .. versionadded:: 1.8.0

    :attr:`minimum_height` is a readonly
    :class:`~kivy.properties.AliasProperty`.

    .. warning::
        :attr:`minimum_width` is calculated based on :attr:`width` therefore
        code like this will lead to an infinite loop::

            <FancyTextInput>:
                height: self.minimum_height
                width: self.height
    '''

    line_spacing = NumericProperty(0)
    '''Space taken up between the lines.

    .. versionadded:: 1.8.0

    :attr:`line_spacing` is a :class:`~kivy.properties.NumericProperty` and
    defaults to 0.
    '''

    lines_to_scroll = BoundedNumericProperty(3, min=1)
    '''Set how many lines will be scrolled at once when using the mouse scroll
    wheel.

    .. versionadded:: 2.2.0

    :attr:`lines_to_scroll is a
    :class:`~kivy.properties.BoundedNumericProperty` and defaults to 3, the
    minimum is 1.
    '''

    input_filter = ObjectProperty(None, allownone=True)
    # TODO: re-add (or not) the input_filter into the new textinput
    ''' Filters the input according to the specified mode, if not None. If
    None, no filtering is applied.

    .. versionadded:: 1.9.0

    :attr:`input_filter` is an :class:`~kivy.properties.ObjectProperty` and
    defaults to `None`. Can be one of `None`, `'int'` (string), or `'float'`
    (string), or a callable. If it is `'int'`, it will only accept numbers.
    If it is `'float'` it will also accept a single period. Finally, if it is
    a callable it will be called with two parameters; the string to be added
    and a bool indicating whether the string is a result of undo (True). The
    callable should return a new substring that will be used instead.
    '''

    handle_image_middle = StringProperty(
        'atlas://data/images/defaulttheme/selector_middle')
    '''Image used to display the middle handle on the TextInput for cursor
    positioning.

    .. versionadded:: 1.8.0

    :attr:`handle_image_middle` is a :class:`~kivy.properties.StringProperty`
    and defaults to 'atlas://data/images/defaulttheme/selector_middle'.
    '''

    def on_handle_image_middle(self, instance, value):
        if self._handle_middle:
            self._handle_middle.source = value

    handle_image_left = StringProperty(
        'atlas://data/images/defaulttheme/selector_left')
    '''Image used to display the Left handle on the TextInput for selection.

    .. versionadded:: 1.8.0

    :attr:`handle_image_left` is a :class:`~kivy.properties.StringProperty` and
    defaults to 'atlas://data/images/defaulttheme/selector_left'.
    '''

    def on_handle_image_left(self, instance, value):
        if self._handle_left:
            self._handle_left.source = value

    handle_image_right = StringProperty(
        'atlas://data/images/defaulttheme/selector_right')
    '''Image used to display the Right handle on the TextInput for selection.

    .. versionadded:: 1.8.0

    :attr:`handle_image_right` is a
    :class:`~kivy.properties.StringProperty` and defaults to
    'atlas://data/images/defaulttheme/selector_right'.
    '''

    def on_handle_image_right(self, instance, value):
        if self._handle_right:
            self._handle_right.source = value

    write_tab = BooleanProperty(True)
    '''Whether the tab key should move focus to the next widget or if it should
    enter a tab in the :class:`TextInput`. If `True` a tab will be written,
    otherwise, focus will move to the next widget.

    .. versionadded:: 1.9.0

    :attr:`write_tab` is a :class:`~kivy.properties.BooleanProperty` and
    defaults to `True`.
    '''


if __name__ == '__main__':
    from textwrap import dedent
    from kivy.app import App
    from kivy.uix.boxlayout import BoxLayout
    from kivy.lang import Builder

    KV = dedent(r'''
    #:set font_size '20dp'

    BoxLayout:
        orientation: 'vertical'
        padding: '20dp'
        spacing: '10dp'
        TextInput:
            font_size: font_size
            size_hint_y: None
            height: self.minimum_height
            multiline: False
            text: 'monoline'

        TextInput:
            size_hint_y: None
            font_size: font_size
            height: self.minimum_height
            multiline: False
            password: True
            password_mask: '•'
            text: 'password'

        TextInput:
            font_size: font_size
            size_hint_y: None
            height: self.minimum_height
            multiline: False
            readonly: True
            text: 'readonly'

        TextInput:
            font_size: font_size
            size_hint_y: None
            height: self.minimum_height
            multiline: False
            disabled: True
            text: 'disabled'

        TextInput:
            font_size: font_size
            hint_text: 'normal with hint text'

        TextInput:
            font_size: font_size
            text: 'default'

        TextInput:
            font_size: font_size
            text: 'bubble & handles'
            use_bubble: True
            use_handles: True

        TextInput:
            font_size: font_size
            text: 'no wrap'
            do_wrap: False

        TextInput:
            font_size: font_size
            text: 'multiline\nreadonly'
            disabled: app.time % 5 < 2.5
    ''')

    class TextInputApp(App):
        time = NumericProperty()

        def build(self):
            Clock.schedule_interval(self.update_time, 0)
            return Builder.load_string(KV)

        def update_time(self, dt):
            self.time += dt

    TextInputApp().run()
