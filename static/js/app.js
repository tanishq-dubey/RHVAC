$(document).ready(function(){
    //connect to the socket server.
    var socket = io.connect('http://' + document.domain + ':' + location.port);

    //receive details from server
    socket.on('tempHeartbeat', function(msg) {
        console.log("Received temp" + msg.temp);
        $('#curr_temp').html(msg.temp);
    });

    socket.on('statusHeartbeat', function(msg) {
        console.log("Got status heartbeat");
        console.log("Enabled: " + msg.enabled);
        if (msg.enabled === true){
            $("#enabled").prop('checked', true);
        } else {
            $("#enabled").prop('checked', false);
        }

        console.log("Mode: " + msg.desired_mode);
        if (msg.desired_mode === 'Mode.COOL') {
            $("input[name=mode_group][value=0]").prop('checked', true);
        } else if (msg.desired_mode === 'Mode.HEAT') {
            $("input[name=mode_group][value=1]").prop('checked', true);
        } else if (msg.desired_mode === 'Mode.AUTO') {
            $("input[name=mode_group][value=2]").prop('checked', true);
        } else {
            $("input[name=mode_group][value=3]").prop('checked', true);
        }

        console.log("State: " + msg.current_state);
        if (msg.current_state === 'State.OFF') {
            $('#current_status').html("System Off");

            $('#background').removeClass("light-blue amber").addClass("grey");
            $('#card-temp-color').removeClass("light-blue amber").addClass("grey");
            $('#card-ctrl-color').removeClass("light-blue amber").addClass("grey");
            $('#navbarjs').removeClass("light-blue amber").addClass("grey");

            $('eta-text').html("");
        } else if (msg.current_state === 'State.HEATING') {
            $('#current_status').html("Heating to " + msg.desired_temperature + '&#8457;');

            $('#background').removeClass("light-blue grey").addClass("amber");
            $('#card-temp-color').removeClass("light-blue grey").addClass("amber");
            $('#card-ctrl-color').removeClass("light-blue grey").addClass("amber");
            $('#navbarjs').removeClass("light-blue grey").addClass("amber");

            $('eta-text').html("ETA to temperature: " + msg.time_to_temp + " minutes");
        } else if (msg.current_state === 'State.COOLING') {
            $('#current_status').html("Cooling to " + msg.desired_temperature + '&#8457;');

            $('#background').removeClass("amber grey").addClass("light-blue");
            $('#card-temp-color').removeClass("amber grey").addClass("light-blue");
            $('#card-ctrl-color').removeClass("amber grey").addClass("light-blue");
            $('#navbarjs').removeClass("amber grey").addClass("light-blue");

            $('eta-text').html("ETA to temperature: " + msg.time_to_temp + " minutes");
        } else if (msg.current_state === 'State.FAN_ONLY') {
            $('#current_status').html("Fan only mode");

            $('#background').removeClass("light-blue amber").addClass("blue-grey");
            $('#card-temp-color').removeClass("light-blue amber").addClass("blue-grey");
            $('#card-ctrl-color').removeClass("light-blue amber").addClass("blue-grey");
            $('#navbarjs').removeClass("light-blue amber").addClass("blue-grey");

            $('eta-text').html("");
        } else if (msg.current_state === 'State.SHUTDOWN') {
            $('eta-text').html("System shutting down");
        }

        $('#curr_temp').html(msg.current_temperature + '&#8457;');
    });

    //TODO: REMOVE
    socket.on('test', function() {
        console.log("test");
    });

    //TODO: REMOVE
    socket.on('connected', function(msg){
        console.log("Connected")
        if (msg.enabled === true){
            $("#enabled").prop('checked', true);
        } else {
            $("#enabled").prop('checked', false);
        }
    });

    $('#enabled').change(function() {
        if(this.checked) {
            socket.emit('enable_system', {data: 'disabled'});
        } else {
            socket.emit('disable_system', {data: 'enabled'});
        }
    });

    $('#desired-temp').change( function() {
        console.log(this.value);
        socket.emit('set_temperature', this.value);
    });

    $("input[name='mode_group']").change(function(e){
        if ($(this).val() == '0') {
            socket.emit('set_mode', 0);
        } else if ($(this).val() == '1') {
            socket.emit('set_mode', 1);
        } else if ($(this).val() == '2') {
            socket.emit('set_mode', 2);
        } else if ($(this).val() == '3') {
            socket.emit('set_mode', 3);
        }
    });
});
