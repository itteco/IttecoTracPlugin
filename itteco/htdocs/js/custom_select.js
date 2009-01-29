mouse_in_out=function(obj){$(obj).toggleClass('focused_drop_down_item');}
clickDDI=function(obj){
    $(obj).siblings().removeClass('selected_drop_down_item');
    $(obj).addClass('selected_drop_down_item');
    var par = $(obj).parent();
    var txt = $(obj).children('em:first').text();
    par.prev().text($(obj).text()); 
    par.next().attr('value',$(obj).attr('empty') ? '' : txt); 
    par.hide();
}

$(document).ready(function(){
    $("div.custom_drop_down_box").children().attr({'a':'x','onmouseover':'mouse_in_out(this);', 'onmouseout':'mouse_in_out(this);','onclick':'clickDDI(this);'});
})